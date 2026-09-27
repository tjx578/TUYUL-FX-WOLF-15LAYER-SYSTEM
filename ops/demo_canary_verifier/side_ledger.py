"""Immutable V31 side ledger for the ENGINEERING_DEMO_CANARY path, and the bounded volume-min canary rule.

Owner decisions (2026-09-27):

- B1: the DEMO path is the existing mechanical EA envelope (EA unchanged) plus this immutable side
  ledger. The ledger binds the V31 lineage to the mechanical chain by explicit identifiers only: V31
  tradeplan candidate id + revision, risk decision id, risk reservation id, exact-S (only from an R9
  artifact), the broker-adaptation result digest, command id, EA receipt ref, and MT5 broker-truth refs.
  Absent exact-S is ``NOT_MEASURED``; it never passes and blocks broker-truth reconciliation.
- B5: bounded volume-min canary, never increase risk. ``canonical_sized_volume < volume_min`` is
  ``NO_SUBMIT``; otherwise the DEMO submitted volume is exactly the broker ``volume_min``. Volumes are
  ``Decimal`` (floats via ``Decimal(str(x))``), never rounded or quantized, and ``volume_min`` only ever
  comes from broker evidence (``SymbolCapability.volume_min`` of the pinned snapshot), never a constant.

Newly defined here (no existing contract): the side-ledger model, the broker-adaptation digest
(canonical :func:`evidence_digest` of the broker-adapted ``ExecutionCommandV1`` with its signature
excluded), and the bounded-volume decision. The ledger is evidence, never submit authority.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from contracts.mt5_execution_protocol import AccountSnapshotV1, CommandGuards, CommandSource, ExecutionCommandV1
from ops.mt5_mcp.report_integrity import evidence_digest

SIDE_LEDGER_SCHEMA: Final = "wolf15.demo-canary.v31-side-ledger.v1"
DEMO_PATH_LABEL: Final = "ENGINEERING_DEMO_CANARY"
BOUNDED_CANARY_REASON: Final = "BOUNDED_CANARY_DOWNSIZE_TO_VOLUME_MIN"
EXACT_S_MEASURED: Final = "MEASURED"
EXACT_S_NOT_MEASURED: Final = "NOT_MEASURED"
NO_SUBMIT: Final = "NO_SUBMIT"
SUBMIT_VOLUME_MIN: Final = "SUBMIT_VOLUME_MIN"
CLAIM_BOUNDARY: Final = {
    "PATH_LABEL": DEMO_PATH_LABEL,
    "EA_NATIVE_V31_SCORECARD": "NOT_PROVEN",
    "PRODUCTION_READY": False,
}
_SHA256 = r"^sha256:[0-9a-f]{64}$"
_TICKET_REF = r"^[0-9a-f]{16}$"


def evidence_decimal(value: Any) -> Decimal | None:
    """Exact Decimal of an evidence number (float via ``Decimal(str(x))``); ``None`` if not a finite number."""

    if isinstance(value, bool):
        return None
    try:
        if isinstance(value, Decimal):
            result = value
        elif isinstance(value, float):
            result = Decimal(str(value))
        elif isinstance(value, int | str):
            result = Decimal(value)
        else:
            return None
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def _volume(value: Any) -> Any:
    result = evidence_decimal(value)
    return value if result is None else result


Volume = Annotated[Decimal, BeforeValidator(_volume), Field(gt=0, allow_inf_nan=False)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ExactSRefV1(_Strict):
    """Exact-S identity. Valid only when it was produced by an R9 artifact."""

    source_artifact: Literal["R9"]
    r9_artifact_sha256: str = Field(pattern=_SHA256)
    exact_s_id: str = Field(min_length=3, max_length=200)
    exact_s_sha256: str = Field(pattern=_SHA256)


class BrokerTruthRefsV1(_Strict):
    """MT5 broker-truth refs as ticket fingerprints (``ops.mt5_mcp.reconcile._fingerprint``); never raw tickets."""

    order_ref: str | None = Field(default=None, pattern=_TICKET_REF)
    deal_ref: str | None = Field(default=None, pattern=_TICKET_REF)
    position_ref: str | None = Field(default=None, pattern=_TICKET_REF)


class V31SideLedgerV1(_Strict):
    """One immutable side-ledger row joining the V31 lineage to one ENGINEERING_DEMO_CANARY command."""

    schema_version: Literal["wolf15.demo-canary.v31-side-ledger.v1"]
    path_label: Literal["ENGINEERING_DEMO_CANARY"]
    tradeplan_candidate_id: str = Field(min_length=3, max_length=200)
    tradeplan_candidate_revision: int = Field(ge=1)
    risk_decision_id: str = Field(min_length=3, max_length=200)
    risk_reservation_id: str = Field(min_length=3, max_length=200)
    exact_s: ExactSRefV1 | None = None
    broker_adaptation_digest: str = Field(pattern=_SHA256)
    command_id: str = Field(min_length=3, max_length=64)
    ea_receipt_report_id: str | None = Field(default=None, min_length=3, max_length=64)
    broker_truth: BrokerTruthRefsV1 | None = None
    canonical_sized_volume: Volume
    demo_submitted_volume: Volume
    volume_reason: Literal["BOUNDED_CANARY_DOWNSIZE_TO_VOLUME_MIN"]


def broker_adaptation_digest(command: ExecutionCommandV1) -> str:
    """Canonical digest of the broker-adapted command (signature excluded: it signs, it is not adapted)."""

    return evidence_digest(command.model_dump(mode="json", exclude={"signature"}))


def exact_s_state(ledger: V31SideLedgerV1 | None) -> str:
    return EXACT_S_MEASURED if ledger is not None and ledger.exact_s is not None else EXACT_S_NOT_MEASURED


def bounded_canary_volume(canonical_sized_volume: Decimal, volume_min: Decimal) -> tuple[str, Decimal | None]:
    """B5: ``NO_SUBMIT`` below the broker minimum, otherwise exactly ``volume_min``. Never upsizes."""

    if canonical_sized_volume < volume_min:
        return NO_SUBMIT, None
    return SUBMIT_VOLUME_MIN, volume_min


def evidence_volume_min(snapshot: AccountSnapshotV1 | None, command: ExecutionCommandV1 | None) -> Decimal | None:
    """``volume_min`` of the exactly-one pinned-snapshot capability for the command's symbol pair, else ``None``."""

    if snapshot is None or command is None or command.order is None:
        return None
    matches = [
        item
        for item in snapshot.symbols
        if item.canonical_symbol == command.order.canonical_symbol and item.broker_symbol == command.order.broker_symbol
    ]
    return evidence_decimal(matches[0].volume_min) if len(matches) == 1 else None


def check_ledger_command_binding(ledger: V31SideLedgerV1, command: ExecutionCommandV1, refusals: set[str]) -> None:
    """The ledger joins the command only by explicit identifiers; any difference is a refusal/break."""

    source, guards = command.source, command.guards
    plan_id = source.block_id if isinstance(source, CommandSource) else None
    reservation_id = guards.risk_reservation_id if isinstance(guards, CommandGuards) else None
    if ledger.command_id != str(command.command_id):
        refusals.add("V31_LEDGER_COMMAND_ID_MISMATCH")
    if plan_id is None or ledger.tradeplan_candidate_id != plan_id:
        refusals.add("V31_LEDGER_TRADEPLAN_MISMATCH")
    if reservation_id is None or ledger.risk_reservation_id != reservation_id:
        refusals.add("V31_LEDGER_RISK_RESERVATION_MISMATCH")
    if ledger.broker_adaptation_digest != broker_adaptation_digest(command):
        refusals.add("V31_LEDGER_BROKER_ADAPTATION_DIGEST_MISMATCH")


def check_bounded_volume(
    ledger: V31SideLedgerV1, volume_min: Decimal | None, command: ExecutionCommandV1 | None, refusals: set[str]
) -> None:
    """Refuse anything but ``demo_submitted_volume == volume_min <= canonical_sized_volume == ...`` on the command."""

    if volume_min is None:
        refusals.add("BROKER_VOLUME_MIN_EVIDENCE_MISSING")
        return
    canonical = ledger.canonical_sized_volume
    submitted = ledger.demo_submitted_volume
    decision, allowed = bounded_canary_volume(canonical, volume_min)
    if decision == NO_SUBMIT:
        refusals.add("CANONICAL_VOLUME_BELOW_BROKER_MIN")
    if submitted > volume_min:
        refusals.add("DEMO_SUBMITTED_VOLUME_EXCEEDS_VOLUME_MIN")
    if submitted > canonical:
        refusals.add("DEMO_SUBMITTED_VOLUME_EXCEEDS_CANONICAL")
    if allowed is None or submitted != allowed:
        refusals.add("DEMO_SUBMITTED_VOLUME_NOT_VOLUME_MIN")
    if command is not None and command.order is not None and evidence_decimal(command.order.volume) != submitted:
        refusals.add("COMMAND_VOLUME_NOT_DEMO_SUBMITTED_VOLUME")


__all__ = [
    "BOUNDED_CANARY_REASON",
    "CLAIM_BOUNDARY",
    "DEMO_PATH_LABEL",
    "EXACT_S_MEASURED",
    "EXACT_S_NOT_MEASURED",
    "NO_SUBMIT",
    "SIDE_LEDGER_SCHEMA",
    "SUBMIT_VOLUME_MIN",
    "BrokerTruthRefsV1",
    "ExactSRefV1",
    "V31SideLedgerV1",
    "bounded_canary_volume",
    "broker_adaptation_digest",
    "check_bounded_volume",
    "check_ledger_command_binding",
    "evidence_decimal",
    "evidence_volume_min",
    "exact_s_state",
]
