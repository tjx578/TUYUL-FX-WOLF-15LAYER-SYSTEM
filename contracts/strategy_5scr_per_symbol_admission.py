"""Per-symbol isolated raw PairAdmission contract (G1/G1b), rule 5scr.pair-admission.per-symbol-isolated.v3.

State is keyed by ``canonical_symbol``. An event for one symbol can open, extend, close, supersede or
suspend only that symbol's lineage. A cross-symbol event never finalizes another symbol's block (G1), and
a direction change supersedes only the same symbol's lineage (G1b). One global safety state is an OVERLAY:
a systemic fault blocks effective progression for every symbol but never rewrites any symbol's lineage.

The legacy global-stream semantics (``5scr.pair-admission.raw-ledger.v2``) are unchanged and remain the
replay semantics for episodes decided under that rule version. Nothing here carries execution, risk or
direction authority, and nothing here ranks symbols.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.strategy_5scr_pair_admission import PAIR_ADMISSION_RULE_VERSION

PER_SYMBOL_ADMISSION_RULE_VERSION = "5scr.pair-admission.per-symbol-isolated.v3"
LEGACY_GLOBAL_STREAM_RULE_VERSION = PAIR_ADMISSION_RULE_VERSION

LineageState = Literal["ACTIVE", "CLOSED", "SUPERSEDED", "SUSPENDED"]
AdmissionDecision = Literal["GRANTED", "REJECTED", "SUSPENDED"]
EffectiveState = Literal["PROGRESSION_ALLOWED", "GLOBAL_SAFETY_VETO"]
GlobalVeto = Literal[
    "KILL_SWITCH_ACTIVE",
    "ACCOUNT_OR_EXECUTOR_IDENTITY_MISMATCH",
    "AUTHENTICATION_OR_SECURITY_FAILURE",
    "DATABASE_OR_GOVERNANCE_FAILURE",
    "SYSTEMIC_MARKET_DATA_AUTHORITY_FAILURE",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PerSymbolAdmissionPolicyV3(_Strict):
    """Explicit, versioned thresholds. No defaults: every value must be bound by the caller's policy."""

    policy_id: str = Field(min_length=3, max_length=120)
    min_duration_seconds: float = Field(gt=0)
    max_gap_seconds: float = Field(gt=0)


class GlobalSafetyStateV1(_Strict):
    """Systemic conditions only. Pair-local faults never belong here."""

    observed_at_utc: datetime
    kill_switch_active: bool
    account_or_executor_identity_ok: bool
    authentication_ok: bool
    database_and_governance_ok: bool
    market_data_authority_ok: bool

    @property
    def vetoes(self) -> tuple[GlobalVeto, ...]:
        found: list[GlobalVeto] = []
        if self.kill_switch_active:
            found.append("KILL_SWITCH_ACTIVE")
        if not self.account_or_executor_identity_ok:
            found.append("ACCOUNT_OR_EXECUTOR_IDENTITY_MISMATCH")
        if not self.authentication_ok:
            found.append("AUTHENTICATION_OR_SECURITY_FAILURE")
        if not self.database_and_governance_ok:
            found.append("DATABASE_OR_GOVERNANCE_FAILURE")
        if not self.market_data_authority_ok:
            found.append("SYSTEMIC_MARKET_DATA_AUTHORITY_FAILURE")
        return tuple(found)


class SymbolAdmissionLineageV3(_Strict):
    canonical_symbol: str = Field(min_length=3, max_length=32)
    rule_version: Literal["5scr.pair-admission.per-symbol-isolated.v3"] = PER_SYMBOL_ADMISSION_RULE_VERSION
    lineage_id: str = Field(pattern=r"^5scr-symbol-lineage:[0-9a-f]{32}$")
    direction: Literal["BUY", "SELL"] | None
    deployment_id: str
    opened_at: datetime
    last_event_at: datetime
    closed_at: datetime | None
    superseded_by: str | None
    state: LineageState
    state_reason_code: str | None
    event_count: int = Field(ge=1)
    effective_ticks: int = Field(ge=1)
    max_gap_seconds: float = Field(ge=0)
    source_event_ids: tuple[str, ...]
    decision: AdmissionDecision | None  # None = no decision yet; reason_code says why (e.g. PENDING_THRESHOLD)
    reason_code: str
    granted_at: datetime | None
    execution_authority: Literal[False] = False
    risk_authority: Literal[False] = False

    @model_validator(mode="after")
    def _consistent(self) -> SymbolAdmissionLineageV3:
        if (self.state == "ACTIVE") != (self.closed_at is None):
            raise ValueError("only ACTIVE lineages are open")
        if (self.state == "SUPERSEDED") != (self.superseded_by is not None):
            raise ValueError("superseded_by is required exactly for SUPERSEDED lineages")
        if (self.decision == "GRANTED") != (self.granted_at is not None):
            raise ValueError("granted_at is required exactly for GRANTED lineages")
        if len(self.source_event_ids) != self.event_count:
            raise ValueError("every lineage event must be identified")
        return self


class PerSymbolAdmissionEvaluationV3(_Strict):
    rule_version: Literal["5scr.pair-admission.per-symbol-isolated.v3"] = PER_SYMBOL_ADMISSION_RULE_VERSION
    policy: PerSymbolAdmissionPolicyV3
    evaluated_at_utc: datetime
    universe: tuple[str, ...]
    global_vetoes: tuple[GlobalVeto, ...]
    effective_state: EffectiveState
    progression_allowed: bool
    effective_grants: tuple[str, ...]
    lineages: dict[str, tuple[SymbolAdmissionLineageV3, ...]]
    symbol_faults: dict[str, str]
    ignored_out_of_universe_events: int = Field(ge=0)
    ignored_non_authority_events: int = Field(ge=0)
    duplicate_events: int = Field(ge=0)
    ranking: Literal[None] = None
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _keyed_by_universe(self) -> PerSymbolAdmissionEvaluationV3:
        if set(self.lineages) != set(self.universe):
            raise ValueError("every universe symbol has exactly one lineage entry")
        if not set(self.symbol_faults) <= set(self.universe):
            raise ValueError("symbol faults are universe-scoped")
        for symbol, items in self.lineages.items():
            if any(item.canonical_symbol != symbol for item in items):
                raise ValueError("a lineage is stored under a different symbol")
        vetoed = bool(self.global_vetoes)
        if self.progression_allowed == vetoed or self.effective_state != (
            "GLOBAL_SAFETY_VETO" if vetoed else "PROGRESSION_ALLOWED"
        ):
            raise ValueError("effective state must follow the global safety overlay")
        granted = tuple(
            item.lineage_id for items in self.lineages.values() for item in items if item.decision == "GRANTED"
        )
        if self.effective_grants != (() if vetoed else granted):
            raise ValueError("grants are effective only while no global veto is active")
        return self


__all__ = [
    "LEGACY_GLOBAL_STREAM_RULE_VERSION",
    "PER_SYMBOL_ADMISSION_RULE_VERSION",
    "GlobalSafetyStateV1",
    "PerSymbolAdmissionEvaluationV3",
    "PerSymbolAdmissionPolicyV3",
    "SymbolAdmissionLineageV3",
]
