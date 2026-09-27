"""Immutable V31 side ledger for the ENGINEERING_DEMO_CANARY path, and the bounded volume-min canary rule.

Owner decisions (2026-09-27):

- B1: the DEMO path is the existing mechanical EA envelope (EA unchanged) plus this immutable side
  ledger. The ledger binds the V31 lineage to the mechanical chain by explicit identifiers only: V31
  tradeplan candidate id + revision, risk decision id, risk reservation id, exact-S (only from an R9
  artifact), the adapted-command provenance digest, command id, EA receipt ref, and MT5 broker-truth refs.
  Absent exact-S is ``NOT_MEASURED``; it never passes and blocks broker-truth reconciliation.
- Exact-S basis (R9EnvelopeV1, owner FROZEN 2026-09-28, ``contracts.r9_envelope_v1``): exact-S is
  ``MEASURED`` only when ``verify_r9_envelope_v1(envelope, artifact_bytes).exact_s_accepted`` (the sole final
  authority; the R9 artifact bytes are required) AND the ledger's ``exact_s_id``/``exact_s_sha256`` equal the
  envelope's ``snapshot_s`` and its ``r9_artifact_sha256`` equals ``envelope.artifact_sha256``. A hash alone
  never passes. ``R9_ENVELOPE_STATUS`` is ``FROZEN``, pinned to the frozen schema sha256; the pin is
  re-verified against ``docs/governance/r9-envelope-v1.md`` at every use (fail closed), and
  :func:`g6_readiness` is ready only for FROZEN + a holding pin + an accepted verdict + broker truth reconciled.
- B5: bounded volume-min canary, never increase risk. ``canonical_sized_volume < volume_min`` is
  ``NO_SUBMIT``; otherwise the DEMO submitted volume is exactly the broker ``volume_min``. Volumes are
  ``Decimal`` (floats via ``Decimal(str(x))``), never rounded or quantized, and ``volume_min`` only ever
  comes from broker evidence (``SymbolCapability.volume_min`` of the pinned snapshot), never a constant.

Newly defined here (no existing contract): the side-ledger model, the adapted-command provenance digest
(:func:`evidence_digest` of the broker-adapted ``ExecutionCommandV1`` with its signature excluded), and the
bounded-volume decision. The provenance digest is an integrity/provenance digest only: it is not a canonical
broker-adaptation digest and not a signature authority until a broker-adaptation contract exists. The
ledger is evidence, never submit authority.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError

from contracts.mt5_execution_protocol import AccountSnapshotV1, CommandGuards, CommandSource, ExecutionCommandV1
from contracts.r9_envelope_v1 import (
    R9EnvelopeV1,
    R9EnvelopeVerdictV1,
    Sha256Hex,
    SnapshotId,
    verify_r9_envelope_v1,
)
from ops.mt5_mcp.report_integrity import evidence_digest

SIDE_LEDGER_SCHEMA: Final = "wolf15.demo-canary.v31-side-ledger.v1"
DEMO_PATH_LABEL: Final = "ENGINEERING_DEMO_CANARY"
BOUNDED_CANARY_REASON: Final = "BOUNDED_CANARY_DOWNSIZE_TO_VOLUME_MIN"
EXACT_S_MEASURED: Final = "MEASURED"
EXACT_S_NOT_MEASURED: Final = "NOT_MEASURED"
NO_SUBMIT: Final = "NO_SUBMIT"
SUBMIT_VOLUME_MIN: Final = "SUBMIT_VOLUME_MIN"
R9_ENVELOPE_NOT_FROZEN: Final = "NOT_FROZEN"
R9_ENVELOPE_FROZEN: Final = "FROZEN"
# Owner FREEZE 2026-09-28 of R9EnvelopeV1 (docs/governance/r9-envelope-v1.md section 8).
R9_ENVELOPE_STATUS: Final = R9_ENVELOPE_FROZEN
R9_ENVELOPE_FROZEN_SCHEMA_SHA256: Final = "10732eebab7e8a3a9270be6d378689e6160bd7a8087520ee2d86bf156e7588a2"
# The freeze record's own pin of sections 1-7 (from "## 1. Purpose" up to "\n## 8. Freeze record").
R9_ENVELOPE_FROZEN_NORMATIVE_SPAN_SHA256: Final = "c9663fa7a752baa8f8723ef0241980d7fc9a55938ff480dc5703564e4e31b96f"
R9_ENVELOPE_DOC_PATH: Path = Path(__file__).resolve().parents[2] / "docs" / "governance" / "r9-envelope-v1.md"
G6_READY_REASON: Final = "READY"
G6_NOT_READY_R9_ENVELOPE: Final = "R9_ENVELOPE_NOT_FROZEN"
G6_NOT_READY_R9_ENVELOPE_UNRECOGNIZED: Final = "R9_ENVELOPE_STATUS_UNRECOGNIZED"
G6_NOT_READY_R9_FROZEN_PIN: Final = "R9_ENVELOPE_FROZEN_PIN_MISMATCH"
G6_NOT_READY_R9_EXACT_S: Final = "R9_EXACT_S_NOT_ACCEPTED"
G6_NOT_READY_BROKER_TRUTH: Final = "BROKER_TRUTH_NOT_RECONCILED"
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
    """Exact-S identity, reusing the frozen R9EnvelopeV1 types: ``exact_s_id``/``exact_s_sha256`` are the envelope's
    ``snapshot_s.snapshot_id``/``snapshot_sha256`` and ``r9_artifact_sha256`` is its ``artifact_sha256``."""

    source_artifact: Literal["R9"]
    r9_artifact_sha256: Sha256Hex
    exact_s_id: SnapshotId
    exact_s_sha256: Sha256Hex


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
    adapted_command_provenance_digest: str = Field(pattern=_SHA256)
    command_id: str = Field(min_length=3, max_length=64)
    ea_receipt_report_id: str | None = Field(default=None, min_length=3, max_length=64)
    broker_truth: BrokerTruthRefsV1 | None = None
    canonical_sized_volume: Volume
    demo_submitted_volume: Volume
    volume_reason: Literal["BOUNDED_CANARY_DOWNSIZE_TO_VOLUME_MIN"]


def adapted_command_provenance_digest(command: ExecutionCommandV1) -> str:
    """Integrity/provenance digest of the broker-adapted command (signature excluded).

    Integrity/provenance only until a broker-adaptation contract exists: it is not a canonical
    broker-adaptation digest and never a signature authority.
    """

    return evidence_digest(command.model_dump(mode="json", exclude={"signature"}))


def check_exact_s_binding(exact_s: ExactSRefV1, envelope: R9EnvelopeV1, refusals: set[str]) -> None:
    """The ledger's exact-S is the envelope's S and R9 artifact, reused exactly; never a separate identity."""

    if exact_s.exact_s_id != envelope.snapshot_s.snapshot_id:
        refusals.add("V31_LEDGER_EXACT_S_ID_MISMATCH")
    if exact_s.exact_s_sha256 != envelope.snapshot_s.snapshot_sha256:
        refusals.add("V31_LEDGER_EXACT_S_SHA256_MISMATCH")
    if exact_s.r9_artifact_sha256 != envelope.artifact_sha256:
        refusals.add("V31_LEDGER_R9_ARTIFACT_SHA256_MISMATCH")


def verify_exact_s(
    ledger: V31SideLedgerV1 | None, r9_envelope: Any, r9_artifact_bytes: bytes | None
) -> tuple[str, R9EnvelopeVerdictV1 | None, set[str]]:
    """Exact-S decision: ``(state, R9 verdict, ledger binding refusals)``. Fail closed.

    ``MEASURED`` only when the R9 verifier verdict accepts (``verify_r9_envelope_v1`` with the artifact bytes, the
    only final authority) and the ledger's exact-S binds that envelope exactly. No envelope means no verdict.
    """

    refusals: set[str] = set()
    if r9_envelope is None:
        return EXACT_S_NOT_MEASURED, None, refusals
    verdict = verify_r9_envelope_v1(r9_envelope, r9_artifact_bytes)
    exact_s = ledger.exact_s if ledger is not None else None
    if exact_s is not None:
        try:
            model = R9EnvelopeV1.model_validate(r9_envelope)
        except ValidationError:
            model = None
        if model is not None:
            check_exact_s_binding(exact_s, model, refusals)
    measured = exact_s is not None and verdict.exact_s_accepted is True and not refusals
    return (EXACT_S_MEASURED if measured else EXACT_S_NOT_MEASURED), verdict, refusals


def r9_envelope_frozen_pin_holds(path: Path | None = None) -> bool:
    """Re-verify at use that the R9 schema document carries the owner freeze record for the pinned schema sha256.

    Fail closed: an unreadable document, a missing ``frozen_schema_sha256``/``envelope_status`` line, or sections 1-7
    that differ from the frozen normative span all mean the pin does not hold.
    """

    try:
        raw = (R9_ENVELOPE_DOC_PATH if path is None else path).read_bytes()
        text = raw.decode("utf-8")
        span = raw[raw.index(b"## 1. Purpose") : raw.index(b"\n## 8. Freeze record")]
    except (OSError, UnicodeDecodeError, ValueError):
        return False
    return (
        f"\nfrozen_schema_sha256           = {R9_ENVELOPE_FROZEN_SCHEMA_SHA256}\n" in text
        and "\nenvelope_status                = FROZEN\n" in text
        and hashlib.sha256(span).hexdigest() == R9_ENVELOPE_FROZEN_NORMATIVE_SPAN_SHA256
    )


def g6_readiness(
    r9_envelope_status: str, *, frozen_pin_holds: bool, exact_s_accepted: bool, broker_truth_reconciled: bool
) -> tuple[bool, str]:
    """Exact-S G6 qualification, fail-closed.

    Ready only for ``FROZEN`` with a holding frozen pin, an accepted R9 verifier verdict, and broker truth
    reconciled. The first failing condition is the reason.
    """

    if r9_envelope_status == R9_ENVELOPE_NOT_FROZEN:
        return False, G6_NOT_READY_R9_ENVELOPE
    if r9_envelope_status != R9_ENVELOPE_FROZEN:
        return False, G6_NOT_READY_R9_ENVELOPE_UNRECOGNIZED
    if frozen_pin_holds is not True:
        return False, G6_NOT_READY_R9_FROZEN_PIN
    if exact_s_accepted is not True:
        return False, G6_NOT_READY_R9_EXACT_S
    if broker_truth_reconciled is not True:
        return False, G6_NOT_READY_BROKER_TRUTH
    return True, G6_READY_REASON


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
    if ledger.adapted_command_provenance_digest != adapted_command_provenance_digest(command):
        refusals.add("V31_LEDGER_ADAPTED_COMMAND_PROVENANCE_MISMATCH")


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
    "G6_NOT_READY_BROKER_TRUTH",
    "G6_NOT_READY_R9_ENVELOPE",
    "G6_NOT_READY_R9_ENVELOPE_UNRECOGNIZED",
    "G6_NOT_READY_R9_EXACT_S",
    "G6_NOT_READY_R9_FROZEN_PIN",
    "G6_READY_REASON",
    "NO_SUBMIT",
    "R9_ENVELOPE_DOC_PATH",
    "R9_ENVELOPE_FROZEN",
    "R9_ENVELOPE_FROZEN_NORMATIVE_SPAN_SHA256",
    "R9_ENVELOPE_FROZEN_SCHEMA_SHA256",
    "R9_ENVELOPE_NOT_FROZEN",
    "R9_ENVELOPE_STATUS",
    "SIDE_LEDGER_SCHEMA",
    "SUBMIT_VOLUME_MIN",
    "BrokerTruthRefsV1",
    "ExactSRefV1",
    "R9EnvelopeVerdictV1",
    "V31SideLedgerV1",
    "adapted_command_provenance_digest",
    "bounded_canary_volume",
    "check_bounded_volume",
    "check_exact_s_binding",
    "check_ledger_command_binding",
    "evidence_decimal",
    "evidence_volume_min",
    "g6_readiness",
    "r9_envelope_frozen_pin_holds",
    "verify_exact_s",
]
