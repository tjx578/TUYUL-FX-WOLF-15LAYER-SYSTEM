"""Offline broker-truth reconciliation of one DEMO-canary command chain.

Chain, every hop joined only by explicit identifiers::

    TradePlan (tradeplan_id, tradeplan_revision)
      -> RiskDecision (risk_decision_id == guards.risk_reservation_id; tradeplan_id == source.block_id)
      -> broker-adapted command (ExecutionCommandV1.command_id + idempotency_key)
      -> EA receipt (ExecutionReportV1 command_id/idempotency_key; broker.order_ticket/deal_ticket/position_id)
      -> MT5 order (ticket) -> deal (ticket, order, position_id) -> position (identifier)

Reused, not redefined:
- ``contracts.mt5_execution_protocol``: ``ExecutionCommandV1``, ``ExecutionReportV1`` (EA receipt).
- ``execution.mt5_risk_command_producer``: tradeplan_id is carried as ``source.block_id`` and the
  risk decision as ``guards.risk_reservation_id`` (``contracts.strategy_5scr_risk_reservation``).
- ``ops.mt5_mcp.reconcile``: the exact broker measurement gate over the read-only MCP export,
  ticket fingerprints (raw broker tickets never appear in the report), record time parsing,
  and process exit codes.
- EA ledger rows from ``Wolf15_DumbExecutor_Demo.mq5`` ``AppendLedger``
  (``timestamp;command_id;state;detail``; ``PERSIST_BEFORE_ORDERSEND``/``ATTEMPT_1_OF_1`` is written
  only after the final OrderCheck preflight passed, immediately before the single ``OrderSend``).

Newly defined here (no existing export contract): the minimal TradePlan/RiskDecision reference
projections, the chain-evidence bundle, and the acceptance report. MT5 has no broker-side client
order id in the MCP export (no ``comment`` field), so the command's ``idempotency_key`` is the
client-order identity and the broker join is by EA-reported tickets only.

ENGINEERING_DEMO_CANARY path (owner B1/B5, see ``side_ledger``): the mechanical chain above is joined
to the V31 lineage only through the immutable ``v31_side_ledger`` section, by explicit identifiers
(tradeplan candidate id + revision, risk decision id, risk reservation id, command id, adapted-command
provenance digest (integrity/provenance only, never a broker-adaptation or signature authority), EA receipt
report id, broker-truth ticket fingerprints). A missing ledger is ``NOT_EXECUTED``,
a mismatch is a ``V31_LEDGER_*`` break, and absent exact-S is ``NOT_MEASURED``: none of them pass.
The bounded volume-min canary is re-verified against the pinned snapshot's ``volume_min`` and the
broker-truth order volume. The report's claim boundary is fixed: ``EA_NATIVE_V31_SCORECARD`` is
``NOT_PROVEN`` and ``PRODUCTION_READY`` is ``False``. Exact-S is accepted ONLY by the frozen R9EnvelopeV1
verifier: the evidence carries the envelope (``r9_envelope``) and the R9 artifact bytes (``r9_artifact_b64``,
base64), the verifier verdict over both must accept, and the ledger's exact-S must be the envelope's S and artifact
hash (``side_ledger.verify_exact_s``, the only module that calls the R9 verifier). A missing envelope or missing bytes is
``NOT_EXECUTED``/``NOT_MEASURED``; a rejected verdict is an ``R9_EXACT_S_NOT_ACCEPTED`` break. ``G6_READY`` is
``True`` only for ``r9_envelope_status == "FROZEN"`` with the frozen pin re-verified against the schema
document, an accepted verdict, the three owner-D3 candidate bindings, and ``BROKER_TRUTH_RECONCILED``;
``G6_READY_REASON`` names the first failure.

D3 candidate bindings (``side_ledger.candidate_binding_failures``; required ``candidate_manifest`` section, missing is
``NOT_EXECUTED``): ``SNAPSHOT_BINDING_MISMATCH`` (R9 S == manifest pinned S == ledger exact-S == command snapshot id ==
pinned snapshot id), ``CAPABILITY_BINDING_MISMATCH`` (R9 volume_min/volume_step == pinned S capability == B5 input,
as ``Decimal(str(x))``), ``SYMBOL_CAPABILITY_BINDING_MISMATCH`` (R9 symbols == manifest/command order/source symbols).
Each failing link is a break (hop ``CANDIDATE_BINDING``, ref = the compared field) and makes ``G6_READY`` false with
that reason. The bound S is the R9 envelope's S; a newer latest snapshot S+1 in the evidence never replaces it.
``runtime_candidate_binding`` reports ``EA_EX5_SHA256``/``EA_PRESET_SHA256``/``DEMO_ACCOUNT_BINDING`` as
``NOT_MEASURED`` unless supplied as evidence; ``G6_READY_FOR_DEMO`` needs ``G6_READY`` and all three measured.

Missing evidence never passes: any absent section yields ``NOT_EXECUTED`` values and
``BROKER_TRUTH_RECONCILED = False``.
"""

from __future__ import annotations

import base64
import binascii
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from contracts.mt5_execution_protocol import (
    AccountSnapshotV1,
    CommandGuards,
    CommandSource,
    ExecutionCommandV1,
    ExecutionReportState,
    ExecutionReportV1,
)
from ops.demo_canary_verifier.envelope import (
    CanaryEnvelopeV1,
    check_command_envelope,
    command_snapshot_id,
    envelope_sha256,
)
from ops.demo_canary_verifier.side_ledger import (
    CANDIDATE_BINDING_REASONS,
    CLAIM_BOUNDARY,
    DEMO_PATH_LABEL,
    EXACT_S_MEASURED,
    R9_ENVELOPE_FROZEN_SCHEMA_SHA256,
    R9_ENVELOPE_STATUS,
    SNAPSHOT_BINDING_MISMATCH,
    BrokerTruthRefsV1,
    CandidateManifestV1,
    R9EnvelopeVerdictV1,
    V31SideLedgerV1,
    bounded_canary_volume,
    candidate_binding_failures,
    check_bounded_volume,
    check_ledger_command_binding,
    evidence_decimal,
    evidence_volume_min,
    g6_readiness,
    parse_r9_envelope,
    r9_envelope_frozen_pin_holds,
    runtime_candidate_binding,
    runtime_candidate_measured,
    verify_exact_s,
)
from ops.mt5_mcp.reconcile import _fingerprint, _measurement_summary, _record_time
from ops.mt5_mcp.report_integrity import evidence_digest

CHAIN_EVIDENCE_SCHEMA: Final = "wolf15.demo-canary.chain-evidence.v1"
CHAIN_REPORT_SCHEMA: Final = "wolf15.demo-canary.chain-reconciliation.v1"
NOT_EXECUTED: Final = "NOT_EXECUTED"

# MetaTrader 5 enumerations (ENUM_DEAL_TYPE, ENUM_DEAL_ENTRY, ENUM_ORDER_STATE).
DEAL_TYPE_TRADE: Final = frozenset({0, 1})  # DEAL_TYPE_BUY, DEAL_TYPE_SELL
DEAL_ENTRY_IN: Final = 0
DEAL_ENTRY_CLOSING: Final = frozenset({1, 3})  # DEAL_ENTRY_OUT, DEAL_ENTRY_OUT_BY
ORDER_STATE_TERMINAL_NO_FILL: Final = frozenset({2, 5, 6})  # CANCELED, REJECTED, EXPIRED
ORDER_STATE_PENDING: Final = frozenset({0, 1})  # STARTED, PLACED
EA_SUBMIT_MARKER: Final = "PERSIST_BEFORE_ORDERSEND"
EA_SUBMIT_DETAIL: Final = "ATTEMPT_1_OF_1"
EA_ORDER_CHECK_PASSED: Final = "DEMO_ORDER_CHECK_PASSED"
EA_FINAL_PREFLIGHT_REJECTED: Final = "DEMO_FINAL_PREFLIGHT_REJECTED"
RECEIPT_FILL_STATES: Final = frozenset({ExecutionReportState.FILLED, ExecutionReportState.PARTIALLY_FILLED})
REQUIRED_SECTIONS: Final = (
    "window",
    "tradeplans",
    "risk_decisions",
    "commands",
    "ea_receipts",
    "ea_ledger",
    "broker",
    "pinned_snapshot",
    "v31_side_ledger",
    "r9_envelope",
    "r9_artifact_b64",
    "candidate_manifest",
)
CANDIDATE_BINDING_SECTIONS: Final = (
    "r9_envelope",
    "candidate_manifest",
    "v31_side_ledger",
    "pinned_snapshot",
    "commands",
)
EXACT_S_MISSING: Final = "v31_side_ledger.exact_s"
R9_ARTIFACT_BYTES_REQUIRED: Final = "ARTIFACT_BYTES_REQUIRED"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class TradePlanRefV1(_Strict):
    """Minimal canonical TradePlan projection needed for the join (not a strategy contract)."""

    tradeplan_id: str = Field(min_length=3, max_length=200)
    tradeplan_revision: int = Field(ge=1)
    content_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class RiskDecisionRefV1(_Strict):
    """Minimal RiskDecision projection; ``risk_decision_id`` is the durable reservation id."""

    risk_decision_id: str = Field(min_length=3, max_length=200)
    tradeplan_id: str = Field(min_length=3, max_length=200)
    tradeplan_revision: int = Field(ge=1)
    decision: Literal["APPROVED", "REJECTED"]


class EaLedgerRowV1(_Strict):
    timestamp_utc: str = Field(min_length=1, max_length=64)
    command_id: str = Field(min_length=1, max_length=64)
    state: str = Field(min_length=1, max_length=64)
    detail: str = Field(max_length=500)


def parse_ea_ledger_csv(text: str) -> list[dict[str, str]]:
    """Parse the EA ``demo-ledger.csv`` (``;`` separated, no header) into ledger rows."""

    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split(";", 3)
        if len(parts) != 4:
            raise ValueError("EA_LEDGER_ROW_MALFORMED")
        timestamp, command_id, state, detail = (part.strip() for part in parts)
        rows.append({"timestamp_utc": timestamp, "command_id": command_id, "state": state, "detail": detail})
    return rows


def _int(value: Any) -> int | None:
    return value if type(value) is int else None


class _Breaks:
    def __init__(self) -> None:
        self.items: set[tuple[str, str, str]] = set()

    def add(self, code: str, hop: str, ref: str = "-") -> None:
        self.items.add((code, hop, ref))

    def as_list(self) -> list[dict[str, str]]:
        return [{"code": code, "hop": hop, "ref": ref} for code, hop, ref in sorted(self.items)]


def _parse_list(raw: Any, model: type[BaseModel], hop: str, breaks: _Breaks) -> list[Any]:
    parsed: list[Any] = []
    if not isinstance(raw, list):
        breaks.add("EVIDENCE_SECTION_INVALID", hop)
        return parsed
    for item in raw:
        try:
            parsed.append(model.model_validate(item))
        except ValidationError:
            breaks.add("RECORD_INVALID", hop)
    return parsed


def _section(evidence: Mapping[str, Any], name: str) -> Any:
    value = evidence.get(name)
    return [] if value is None else value


def _window(raw: Any) -> tuple[datetime, datetime] | None:
    if not isinstance(raw, Mapping):
        return None
    try:
        start = datetime.fromisoformat(str(raw["from_utc"]))
        end = datetime.fromisoformat(str(raw["to_utc"]))
    except (KeyError, ValueError):
        return None
    if start.tzinfo is None or end.tzinfo is None or end <= start:
        return None
    return start, end


def _records(broker: Mapping[str, Any], tool: str) -> list[Mapping[str, Any]]:
    payload = broker.get("snapshots", {}).get(tool, {})
    records = payload.get("records") if isinstance(payload, Mapping) else None
    return [record for record in records if isinstance(record, Mapping)] if isinstance(records, list) else []


def _in_window(record: Mapping[str, Any], window_from: datetime) -> bool:
    observed = _record_time(record)
    # Unparseable time stays in scope: fail closed rather than hide a broker entity.
    return observed is None or observed >= window_from


def _command_links(command: ExecutionCommandV1) -> tuple[str | None, str | None]:
    """Return (tradeplan_id, risk_decision_id) exactly as the risk command producer binds them."""

    if isinstance(command.source, CommandSource) and isinstance(command.guards, CommandGuards):
        return command.source.block_id, command.guards.risk_reservation_id
    return None, None


def _join_strategy(
    commands: list[ExecutionCommandV1],
    tradeplans: list[TradePlanRefV1],
    decisions: list[RiskDecisionRefV1],
    breaks: _Breaks,
) -> dict[str, dict[str, str]]:
    hops: dict[str, dict[str, str]] = {}
    plan_keys = Counter((plan.tradeplan_id, plan.tradeplan_revision) for plan in tradeplans)
    for key, count in plan_keys.items():
        if count > 1:
            breaks.add("DUPLICATE_TRADEPLAN_REVISION", "TRADEPLAN", key[0])
    decision_ids = Counter(decision.risk_decision_id for decision in decisions)
    for decision_id, count in decision_ids.items():
        if count > 1:
            breaks.add("DUPLICATE_RISK_DECISION", "RISK_DECISION", decision_id)
    per_plan = Counter(decision.tradeplan_id for decision in decisions if decision.decision == "APPROVED")
    for plan_id, count in per_plan.items():
        if count > 1:
            breaks.add("MULTIPLE_APPROVED_RISK_DECISIONS_FOR_TRADEPLAN", "RISK_DECISION", plan_id)
    used_decisions: set[str] = set()
    for command in commands:
        ref = str(command.command_id)
        state = {"TRADEPLAN": "ABSENT", "RISK_DECISION": "ABSENT"}
        plan_id, decision_id = _command_links(command)
        if plan_id is None or decision_id is None:
            breaks.add("COMMAND_WITHOUT_STRATEGY_LINEAGE", "RISK_DECISION", ref)
            hops[ref] = state
            continue
        matches = [decision for decision in decisions if decision.risk_decision_id == decision_id]
        if len(matches) != 1:
            breaks.add("RISK_DECISION_NOT_FOUND" if not matches else "DUPLICATE_RISK_DECISION", "RISK_DECISION", ref)
            hops[ref] = state
            continue
        decision = matches[0]
        used_decisions.add(decision.risk_decision_id)
        if decision.decision != "APPROVED":
            breaks.add("RISK_DECISION_NOT_APPROVED", "RISK_DECISION", ref)
        elif decision.tradeplan_id != plan_id:
            breaks.add("RISK_DECISION_TRADEPLAN_MISMATCH", "RISK_DECISION", ref)
        else:
            state["RISK_DECISION"] = "JOINED"
        if plan_keys.get((decision.tradeplan_id, decision.tradeplan_revision), 0) == 1:
            state["TRADEPLAN"] = "JOINED"
        else:
            breaks.add("TRADEPLAN_REVISION_NOT_FOUND", "TRADEPLAN", ref)
        hops[ref] = state
    for decision in decisions:
        if decision.decision == "APPROVED" and decision.risk_decision_id not in used_decisions:
            breaks.add("APPROVED_RISK_DECISION_WITHOUT_COMMAND", "RISK_DECISION", decision.risk_decision_id)
    return hops


def _ticket_ref(entity: str, ticket: int) -> str:
    return _fingerprint(entity, ticket)


def reconcile_chain(evidence: Mapping[str, Any], *, envelope: CanaryEnvelopeV1) -> dict[str, Any]:
    """Reconcile exported chain evidence against direct broker truth. Pure; never raises on bad evidence."""

    breaks = _Breaks()
    missing = sorted(name for name in REQUIRED_SECTIONS if evidence.get(name) is None)
    pinned_envelope = envelope_sha256(envelope)
    if evidence.get("schema_version") != CHAIN_EVIDENCE_SCHEMA:
        breaks.add("EVIDENCE_SCHEMA_INVALID", "BUNDLE")
    if evidence.get("envelope_sha256") != pinned_envelope:
        breaks.add("ENVELOPE_SHA256_MISMATCH", "BUNDLE")

    window = _window(evidence.get("window"))
    if window is None and "window" not in missing:
        missing.append("window")

    tradeplans: list[TradePlanRefV1] = _parse_list(
        _section(evidence, "tradeplans"), TradePlanRefV1, "TRADEPLAN", breaks
    )
    decisions: list[RiskDecisionRefV1] = _parse_list(
        _section(evidence, "risk_decisions"), RiskDecisionRefV1, "RISK_DECISION", breaks
    )
    commands: list[ExecutionCommandV1] = _parse_list(
        _section(evidence, "commands"), ExecutionCommandV1, "COMMAND", breaks
    )
    receipts: list[ExecutionReportV1] = _parse_list(
        _section(evidence, "ea_receipts"), ExecutionReportV1, "EA_RECEIPT", breaks
    )
    ledger: list[EaLedgerRowV1] = _parse_list(_section(evidence, "ea_ledger"), EaLedgerRowV1, "EA_LEDGER", breaks)

    # --- command identity and envelope re-check ---------------------------------------------
    by_command: dict[str, ExecutionCommandV1] = {}
    for command in commands:
        ref = str(command.command_id)
        if ref in by_command:
            breaks.add("DUPLICATE_COMMAND_ID", "COMMAND", ref)
        by_command[ref] = command
        refusals: set[str] = set()
        check_command_envelope(command, envelope, refusals)
        for code in refusals:
            breaks.add("ENVELOPE_" + code, "COMMAND", ref)
    idempotency = Counter(command.idempotency_key for command in commands)
    duplicate_keys = sum(count - 1 for count in idempotency.values() if count > 1)
    if duplicate_keys:
        breaks.add("DUPLICATE_IDEMPOTENCY_KEY", "COMMAND")
    one_command: bool | str = NOT_EXECUTED if "commands" in missing else len(commands) == 1 and not duplicate_keys
    if one_command is False:
        breaks.add("NOT_ONE_COMMAND", "COMMAND", str(len(commands)))

    strategy_hops = _join_strategy(commands, tradeplans, decisions, breaks)

    # --- EA receipts ---------------------------------------------------------------------------
    receipts_by_command: dict[str, list[ExecutionReportV1]] = defaultdict(list)
    sequences: dict[tuple[str, int], str] = {}
    for receipt in receipts:
        ref = str(receipt.command_id)
        command = by_command.get(ref)
        if command is None:
            breaks.add("RECEIPT_WITHOUT_COMMAND", "EA_RECEIPT", ref)
            continue
        if receipt.idempotency_key != command.idempotency_key:
            breaks.add("RECEIPT_IDEMPOTENCY_MISMATCH", "EA_RECEIPT", ref)
        if (
            receipt.executor_id != command.executor_binding.executor_id
            or receipt.account_id != command.executor_binding.account_id
        ):
            breaks.add("RECEIPT_BINDING_MISMATCH", "EA_RECEIPT", ref)
        digest = evidence_digest(receipt.model_dump(mode="json", exclude={"report_id"}))
        previous = sequences.setdefault((ref, receipt.sequence), digest)
        if previous != digest:
            breaks.add("RECEIPT_SEQUENCE_CONFLICT", "EA_RECEIPT", ref)
        receipts_by_command[ref].append(receipt)

    # --- EA ledger: submit markers ----------------------------------------------------------------
    markers: dict[str, list[EaLedgerRowV1]] = defaultdict(list)
    for row in ledger:
        if row.state != EA_SUBMIT_MARKER:
            continue
        if row.command_id not in by_command:
            breaks.add("EA_SUBMIT_WITHOUT_COMMAND", "EA_LEDGER", row.command_id)
        markers[row.command_id].append(row)
    submit_count = sum(len(rows) for rows in markers.values())
    retry_markers = sum(1 for rows in markers.values() for row in rows if row.detail != EA_SUBMIT_DETAIL)
    if retry_markers or any(len(rows) > 1 for rows in markers.values()):
        breaks.add("AUTO_RETRY_SUBMIT_OBSERVED", "EA_LEDGER")

    # --- broker truth -------------------------------------------------------------------------------
    broker = evidence.get("broker")
    broker_measured = False
    measurements: dict[str, Any] = {}
    if isinstance(broker, Mapping) and window is not None:
        measurements, broker_measured = _measurement_summary(broker, window_from=window[0], window_to=window[1])
    if broker is not None and not broker_measured and "broker" not in missing:
        missing.append("broker")
    broker_map: Mapping[str, Any] = broker if isinstance(broker, Mapping) and broker_measured else {}

    accounts = _records(broker_map, "mt5_account_get")
    if broker_measured and (len(accounts) != 1 or _int(accounts[0].get("trade_mode")) != 0):
        breaks.add("ACCOUNT_NOT_DEMO", "BROKER")

    window_from = window[0] if window is not None else None
    orders: dict[int, Mapping[str, Any]] = {}
    preexisting = 0
    for tool in ("mt5_orders_get", "mt5_history_orders_get"):
        for record in _records(broker_map, tool):
            ticket = _int(record.get("ticket"))
            if ticket is None:
                continue
            if window_from is not None and not _in_window(record, window_from):
                preexisting += 1
                continue
            orders.setdefault(ticket, record)
    current_order_tickets = {_int(r.get("ticket")) for r in _records(broker_map, "mt5_orders_get")}
    deals: dict[int, Mapping[str, Any]] = {}
    non_trade_deals = 0
    for record in _records(broker_map, "mt5_history_deals_get"):
        ticket = _int(record.get("ticket"))
        if ticket is None:
            continue
        if _int(record.get("type")) not in DEAL_TYPE_TRADE:
            non_trade_deals += 1
            continue
        if window_from is not None and not _in_window(record, window_from):
            preexisting += 1
            continue
        deals[ticket] = record
    positions: dict[int, Mapping[str, Any]] = {}
    for record in _records(broker_map, "mt5_positions_get"):
        identifier = _int(record.get("identifier")) or _int(record.get("ticket"))
        if identifier is not None:
            positions[identifier] = record
    deals_by_order: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for deal in deals.values():
        order_ticket = _int(deal.get("order"))
        if order_ticket is not None:
            deals_by_order[order_ticket].append(deal)

    # Primary orders: only tickets the EA reported for a known command.
    primary: dict[str, set[int]] = defaultdict(set)
    joined_positions: dict[str, set[int]] = defaultdict(set)
    for ref, items in receipts_by_command.items():
        for receipt in items:
            reported_order = receipt.broker.order_ticket
            reported_deal = receipt.broker.deal_ticket
            if reported_order is not None:
                if broker_measured and reported_order not in orders:
                    breaks.add("RECEIPT_ORDER_NOT_AT_BROKER", "MT5_ORDER", ref)
                primary[ref].add(reported_order)
            if reported_deal is not None:
                deal = deals.get(reported_deal)
                if deal is None:
                    if broker_measured:
                        breaks.add("RECEIPT_DEAL_NOT_AT_BROKER", "DEAL", ref)
                else:
                    deal_order = _int(deal.get("order"))
                    if reported_order is not None and deal_order != reported_order:
                        breaks.add("RECEIPT_DEAL_ORDER_MISMATCH", "DEAL", ref)
                    if deal_order is not None:
                        primary[ref].add(deal_order)
            if receipt.broker.position_id is not None:
                joined_positions[ref].add(receipt.broker.position_id)
    primary_owner = {ticket: ref for ref, tickets in primary.items() for ticket in tickets}
    for ref, tickets in primary.items():
        for ticket in tickets:
            for deal in deals_by_order.get(ticket, []):
                position_id = _int(deal.get("position_id"))
                if _int(deal.get("entry")) == DEAL_ENTRY_IN and position_id:
                    joined_positions[ref].add(position_id)
    all_joined_positions = {pid: ref for ref, pids in joined_positions.items() for pid in pids}
    canary_signatures = {
        (command.order.magic, command.order.broker_symbol) for command in commands if command.order is not None
    }

    duplicate_order = sum(max(0, len(tickets) - 1) for tickets in primary.values())
    orphan_order = 0
    order_refs: list[dict[str, str]] = []
    for ticket, record in sorted(orders.items()):
        classification: str
        if ticket in primary_owner:
            classification = "JOINED_PRIMARY"
        elif _int(record.get("position_id")) in all_joined_positions:
            entries = {_int(deal.get("entry")) for deal in deals_by_order.get(ticket, [])}
            if entries and entries <= DEAL_ENTRY_CLOSING:
                classification = "JOINED_CLOSE"
            elif entries:
                classification = "DUPLICATE_ORDER"
                duplicate_order += 1
            else:
                classification = "ORPHAN_ORDER"
                orphan_order += 1
        elif (_int(record.get("magic")), str(record.get("symbol") or "")) in canary_signatures:
            classification = "DUPLICATE_ORDER"
            duplicate_order += 1
        else:
            classification = "ORPHAN_ORDER"
            orphan_order += 1
        order_refs.append({"entity": _ticket_ref("ORDER", ticket), "classification": classification})
        if classification in {"DUPLICATE_ORDER", "ORPHAN_ORDER"}:
            breaks.add(classification, "MT5_ORDER", _ticket_ref("ORDER", ticket))

    unaccounted_fill = 0
    for ticket, deal in sorted(deals.items()):
        order_ticket = _int(deal.get("order"))
        position_id = _int(deal.get("position_id"))
        if order_ticket in primary_owner:
            continue
        if position_id in all_joined_positions and _int(deal.get("entry")) in DEAL_ENTRY_CLOSING:
            continue
        unaccounted_fill += 1
        breaks.add("UNACCOUNTED_BROKER_FILL", "DEAL", _ticket_ref("DEAL", ticket))

    candidate_positions = set(positions) | {
        pid for deal in deals.values() if (pid := _int(deal.get("position_id"))) is not None and pid > 0
    }
    unknown_position = 0
    for position_id in sorted(candidate_positions):
        if position_id not in all_joined_positions:
            unknown_position += 1
            breaks.add("UNKNOWN_POSITION", "POSITION", _ticket_ref("POSITION", position_id))

    # --- per-command chain completeness ----------------------------------------------------------
    chains: list[dict[str, Any]] = []
    for ref, command in sorted(by_command.items()):
        items = receipts_by_command.get(ref, [])
        hops = dict(strategy_hops.get(ref, {"TRADEPLAN": "ABSENT", "RISK_DECISION": "ABSENT"}))
        hops["COMMAND"] = "JOINED"
        hops["EA_RECEIPT"] = "JOINED" if items else "ABSENT"
        if not items:
            breaks.add("COMMAND_WITHOUT_EA_RECEIPT", "EA_RECEIPT", ref)
        tickets = primary.get(ref, set())
        command_deals = [deal for ticket in tickets for deal in deals_by_order.get(ticket, [])]
        pids = joined_positions.get(ref, set())
        broker_effect = bool(tickets or command_deals or pids)
        hops["MT5_ORDER"] = "JOINED" if tickets and tickets <= set(orders) else "ABSENT"
        hops["DEAL"] = "JOINED" if command_deals else "ABSENT"
        hops["POSITION"] = "JOINED" if pids else "ABSENT"

        command_markers = markers.get(ref, [])
        states = {(receipt.state, receipt.reason_code) for receipt in items}
        if broker_effect:
            if len(command_markers) != 1:
                breaks.add("BROKER_EFFECT_WITHOUT_SINGLE_EA_SUBMIT_MARKER", "EA_LEDGER", ref)
            if (ExecutionReportState.SUBMITTING, EA_ORDER_CHECK_PASSED) not in states:
                breaks.add("EA_FINAL_PREFLIGHT_UNEVIDENCED", "EA_RECEIPT", ref)
            if (ExecutionReportState.PREFLIGHT_REJECTED, EA_FINAL_PREFLIGHT_REJECTED) in states:
                breaks.add("BROKER_EFFECT_AFTER_FINAL_PREFLIGHT_REJECT", "EA_RECEIPT", ref)
        if any(receipt.state in RECEIPT_FILL_STATES for receipt in items) and not command_deals:
            breaks.add("RECEIPT_FILL_NOT_AT_BROKER", "DEAL", ref)
        for ticket in tickets:
            record = orders.get(ticket)
            if record is None or deals_by_order.get(ticket):
                continue
            state = _int(record.get("state"))
            pending_ok = ticket in current_order_tickets and state in ORDER_STATE_PENDING
            if not pending_ok and state not in ORDER_STATE_TERMINAL_NO_FILL:
                breaks.add("ORDER_WITHOUT_DEAL", "DEAL", ref)
        if len(pids) > 1:
            breaks.add("MULTIPLE_POSITIONS_FOR_COMMAND", "POSITION", ref)
        for pid in pids:
            closed = any(
                _int(deal.get("position_id")) == pid and _int(deal.get("entry")) in DEAL_ENTRY_CLOSING
                for deal in deals.values()
            )
            if broker_measured and pid not in positions and not closed:
                breaks.add("POSITION_NOT_EVIDENCED", "POSITION", ref)
            open_record = positions.get(pid)
            volume = open_record.get("volume") if open_record is not None else None
            if command.order is not None and isinstance(volume, int | float) and volume > command.order.volume + 1e-9:
                breaks.add("POSITION_VOLUME_EXCEEDS_COMMAND", "POSITION", ref)
        chains.append({"command_id": ref, "hops": hops})

    snapshot: AccountSnapshotV1 | None = None
    if evidence.get("pinned_snapshot") is not None:
        try:
            snapshot = AccountSnapshotV1.model_validate(evidence.get("pinned_snapshot"))
        except ValidationError:
            breaks.add("RECORD_INVALID", "PINNED_SNAPSHOT")
    r9_artifact_bytes = _r9_artifact_bytes(evidence.get("r9_artifact_b64"), breaks)
    side_ledger, ledger_report, exact_s, r9_verdict, b5_volume_min = _reconcile_side_ledger(
        evidence,
        snapshot=snapshot,
        by_command=by_command,
        tradeplans=tradeplans,
        decisions=decisions,
        receipts_by_command=receipts_by_command,
        primary=primary,
        orders=orders,
        deals_by_order=deals_by_order,
        joined_positions=joined_positions,
        broker_measured=broker_measured,
        r9_artifact_bytes=r9_artifact_bytes,
        breaks=breaks,
    )
    if r9_verdict is not None:
        for reason in r9_verdict.failure_reasons:
            if reason == R9_ARTIFACT_BYTES_REQUIRED and "r9_artifact_b64" in missing:
                continue  # absent bytes are missing evidence (NOT_EXECUTED), not a rejected artifact
            breaks.add("R9_EXACT_S_NOT_ACCEPTED", "R9_ENVELOPE", reason)
    if exact_s != EXACT_S_MEASURED and (side_ledger is None or side_ledger.exact_s is None):
        missing.append(EXACT_S_MISSING)
    ledger_joined: bool | str = NOT_EXECUTED if "v31_side_ledger" in missing else ledger_report["status"] == "JOINED"
    candidate_binding = _candidate_binding(
        evidence,
        missing=missing,
        ledger=side_ledger,
        command=by_command.get(side_ledger.command_id) if side_ledger is not None else None,
        snapshot=snapshot,
        b5_volume_min=b5_volume_min,
        breaks=breaks,
    )
    runtime_binding, runtime_valid = runtime_candidate_binding(evidence.get("runtime_candidate_binding"))
    if not runtime_valid:
        breaks.add("RUNTIME_CANDIDATE_BINDING_INVALID", "RUNTIME_CANDIDATE_BINDING")

    canary_orders = sum(len(tickets) for tickets in primary.values()) + sum(
        1 for item in order_refs if item["classification"] == "DUPLICATE_ORDER"
    )
    ledger_missing = "ea_ledger" in missing
    one_submit_max: bool | str
    if ledger_missing or not broker_measured:
        one_submit_max = NOT_EXECUTED
    else:
        one_submit_max = submit_count <= 1 and retry_markers == 0 and canary_orders <= 1
        if not one_submit_max:
            breaks.add("NOT_ONE_SUBMIT_MAX", "EA_LEDGER", str(submit_count))

    def count(value: int) -> int | str:
        return value if broker_measured else NOT_EXECUTED

    missing = sorted(set(missing))
    reconciled = (
        not missing
        and not breaks.items
        and one_command is True
        and one_submit_max is True
        and ledger_joined is True
        and exact_s == EXACT_S_MEASURED
    )
    status = NOT_EXECUTED if missing else ("RECONCILED" if reconciled else "NOT_RECONCILED")
    frozen_pin_holds = r9_envelope_frozen_pin_holds()
    g6_ready, g6_reason = g6_readiness(
        R9_ENVELOPE_STATUS,
        frozen_pin_holds=frozen_pin_holds,
        exact_s_accepted=r9_verdict is not None and r9_verdict.exact_s_accepted,
        snapshot_bound=candidate_binding["SNAPSHOT_BINDING"] is True,
        capability_bound=candidate_binding["CAPABILITY_BINDING"] is True,
        symbol_bound=candidate_binding["SYMBOL_CAPABILITY_BINDING"] is True,
        broker_truth_reconciled=reconciled,
    )
    return {
        "schema_version": CHAIN_REPORT_SCHEMA,
        "envelope_sha256": pinned_envelope,
        "evidence_sha256": _safe_digest(evidence),
        "status": status,
        "acceptance": {
            "ONE_COMMAND": one_command,
            "ONE_SUBMIT_MAX": one_submit_max,
            "DUPLICATE_ORDER": count(duplicate_order),
            "UNKNOWN_POSITION": count(unknown_position),
            "ORPHAN_ORDER": count(orphan_order),
            "UNACCOUNTED_BROKER_FILL": count(unaccounted_fill),
            "V31_SIDE_LEDGER_JOINED": ledger_joined,
            "V31_EXACT_S": exact_s,
            "BROKER_TRUTH_RECONCILED": reconciled,
            "G6_READY": g6_ready,
            "G6_READY_REASON": g6_reason,
        },
        "r9_envelope_status": R9_ENVELOPE_STATUS,
        "r9_exact_s": {
            "frozen_schema_sha256": R9_ENVELOPE_FROZEN_SCHEMA_SHA256,
            "frozen_pin_holds": frozen_pin_holds,
            "verdict": None if r9_verdict is None else r9_verdict.model_dump(mode="json"),
        },
        "v31_side_ledger": ledger_report,
        "candidate_binding": candidate_binding,
        "runtime_candidate_binding": {
            **runtime_binding,
            "G6_READY_FOR_DEMO": g6_ready and runtime_candidate_measured(runtime_binding),
        },
        "missing_evidence": missing,
        "breaks": breaks.as_list(),
        "chains": chains,
        "broker_orders": order_refs,
        "counts": {
            "commands": len(commands),
            "ea_submit_markers": submit_count,
            "historical_preexisting": preexisting,
            "non_trade_deals": non_trade_deals,
        },
        "broker_measurements": measurements,
        "claim_boundary": dict(CLAIM_BOUNDARY),
        "PATH_LABEL": DEMO_PATH_LABEL,
        "EA_NATIVE_V31_SCORECARD": "NOT_PROVEN",
        "SUBMIT_AUTHORITY": False,
        "EXECUTION_READY": False,
        "PRODUCTION_READY": False,
    }


def _single_ref(entity: str, values: set[int]) -> str | None:
    return _ticket_ref(entity, next(iter(values))) if len(values) == 1 else None


def _r9_artifact_bytes(raw: Any, breaks: _Breaks) -> bytes | None:
    """Strict base64 of the R9 source artifact bytes; absent is ``None``, malformed is a break and ``None``."""

    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            return base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError):
            pass
    breaks.add("R9_ARTIFACT_BYTES_INVALID", "R9_ENVELOPE")
    return None


def _reconcile_side_ledger(
    evidence: Mapping[str, Any],
    *,
    snapshot: AccountSnapshotV1 | None,
    by_command: Mapping[str, ExecutionCommandV1],
    tradeplans: list[TradePlanRefV1],
    decisions: list[RiskDecisionRefV1],
    receipts_by_command: Mapping[str, list[ExecutionReportV1]],
    primary: Mapping[str, set[int]],
    orders: Mapping[int, Mapping[str, Any]],
    deals_by_order: Mapping[int, list[Mapping[str, Any]]],
    joined_positions: Mapping[str, set[int]],
    broker_measured: bool,
    r9_artifact_bytes: bytes | None,
    breaks: _Breaks,
) -> tuple[V31SideLedgerV1 | None, dict[str, Any], str, R9EnvelopeVerdictV1 | None, Decimal | None]:
    """B1: the side ledger joins the chain by explicit identifiers. B5: bounded volume-min canary.

    Exact-S comes only from :func:`verify_exact_s` (the frozen R9 verifier verdict over the envelope and its artifact
    bytes, plus the ledger's exact binding to that envelope). Returns ``(ledger, report, exact_s, r9_verdict,
    b5_volume_min)``; ``b5_volume_min`` is the exact value B5 was checked against (pinned S only).
    """

    report: dict[str, Any] = {"status": NOT_EXECUTED, "ledger_sha256": None, "volume_decision": None}
    r9_envelope = evidence.get("r9_envelope")
    raw = evidence.get("v31_side_ledger")
    if raw is None:
        state, verdict, _ = verify_exact_s(None, r9_envelope, r9_artifact_bytes)
        return None, report, state, verdict, None
    try:
        ledger = V31SideLedgerV1.model_validate(raw)
    except ValidationError:
        breaks.add("V31_SIDE_LEDGER_INVALID", "V31_SIDE_LEDGER")
        report["status"] = "INVALID"
        state, verdict, _ = verify_exact_s(None, r9_envelope, r9_artifact_bytes)
        return None, report, state, verdict, None

    exact_s, r9_verdict, found = verify_exact_s(ledger, r9_envelope, r9_artifact_bytes)
    command = by_command.get(ledger.command_id)
    ref = ledger.command_id
    if command is None:
        found.add("V31_LEDGER_COMMAND_ID_MISMATCH")
    else:
        check_ledger_command_binding(ledger, command, found)
        plan_key = (ledger.tradeplan_candidate_id, ledger.tradeplan_candidate_revision)
        if sum(1 for plan in tradeplans if (plan.tradeplan_id, plan.tradeplan_revision) == plan_key) != 1:
            found.add("V31_LEDGER_TRADEPLAN_MISMATCH")
        matches = [item for item in decisions if item.risk_decision_id == ledger.risk_decision_id]
        if (
            len(matches) != 1
            or _command_links(command)[1] != ledger.risk_decision_id
            or (matches[0].tradeplan_id, matches[0].tradeplan_revision) != plan_key
        ):
            found.add("V31_LEDGER_RISK_DECISION_MISMATCH")
        report_ids = {str(item.report_id) for item in receipts_by_command.get(ref, [])}
        if ledger.ea_receipt_report_id is None or ledger.ea_receipt_report_id not in report_ids:
            found.add("V31_LEDGER_EA_RECEIPT_MISMATCH")
        tickets = primary.get(ref, set())
        entry_deals = {
            ticket
            for order in tickets
            for deal in deals_by_order.get(order, [])
            if _int(deal.get("entry")) == DEAL_ENTRY_IN and (ticket := _int(deal.get("ticket"))) is not None
        }
        pids = joined_positions.get(ref, set())
        refs = ledger.broker_truth or BrokerTruthRefsV1()
        expected = (_single_ref("ORDER", tickets), _single_ref("DEAL", entry_deals), _single_ref("POSITION", pids))
        if broker_measured and (
            max(len(tickets), len(entry_deals), len(pids)) > 1
            or (refs.order_ref, refs.deal_ref, refs.position_ref) != expected
        ):
            found.add("V31_LEDGER_BROKER_TRUTH_MISMATCH")
        if snapshot is not None and (
            command_snapshot_id(command) != snapshot.snapshot_id
            or command.executor_binding.executor_id != snapshot.executor_id
            or command.executor_binding.account_id != snapshot.account_id
        ):
            found.add("PINNED_SNAPSHOT_BINDING_MISMATCH")
        for ticket in tickets:
            record = orders.get(ticket)
            if record is not None and evidence_decimal(record.get("volume_initial")) != ledger.demo_submitted_volume:
                found.add("BROKER_ORDER_VOLUME_NOT_DEMO_SUBMITTED_VOLUME")
    volume_min = evidence_volume_min(snapshot, command)
    check_bounded_volume(ledger, volume_min, command, found)
    for code in found:
        breaks.add(code, "V31_SIDE_LEDGER", ref)
    report.update(
        {
            "status": "BROKEN" if found else "JOINED",
            "ledger_sha256": evidence_digest(ledger.model_dump(mode="json")),
            "canonical_sized_volume": str(ledger.canonical_sized_volume),
            "demo_submitted_volume": str(ledger.demo_submitted_volume),
            "broker_volume_min": None if volume_min is None else str(volume_min),
            "volume_decision": (
                None if volume_min is None else bounded_canary_volume(ledger.canonical_sized_volume, volume_min)[0]
            ),
            "volume_reason": ledger.volume_reason,
        }
    )
    return ledger, report, exact_s, r9_verdict, volume_min


def _candidate_binding(
    evidence: Mapping[str, Any],
    *,
    missing: list[str],
    ledger: V31SideLedgerV1 | None,
    command: ExecutionCommandV1 | None,
    snapshot: AccountSnapshotV1 | None,
    b5_volume_min: Decimal | None,
    breaks: _Breaks,
) -> dict[str, Any]:
    """Owner D3: the three candidate bindings, each ``True``/``False``/``NOT_EXECUTED`` (never passes when missing).

    The bound S is the R9 envelope's ``snapshot_s``; nothing else in the evidence (e.g. a latest snapshot) replaces it.
    """

    r9 = parse_r9_envelope(evidence.get("r9_envelope")) if evidence.get("r9_envelope") is not None else None
    manifest: CandidateManifestV1 | None = None
    if evidence.get("candidate_manifest") is not None:
        try:
            manifest = CandidateManifestV1.model_validate(evidence.get("candidate_manifest"))
        except ValidationError:
            breaks.add("CANDIDATE_MANIFEST_INVALID", "CANDIDATE_MANIFEST")
    if manifest is not None and ledger is not None:
        plan_key = (ledger.tradeplan_candidate_id, ledger.tradeplan_candidate_revision)
        if (manifest.tradeplan_candidate_id, manifest.tradeplan_candidate_revision) != plan_key:
            breaks.add("CANDIDATE_MANIFEST_CANDIDATE_MISMATCH", "CANDIDATE_MANIFEST")
    result: dict[str, Any] = {reason.removesuffix("_MISMATCH"): NOT_EXECUTED for reason in CANDIDATE_BINDING_REASONS}
    result["bound_snapshot_s"] = None if r9 is None else r9.snapshot_s.model_dump(mode="json")
    if ledger is None or command is None or snapshot is None:
        return result
    if any(name in missing for name in CANDIDATE_BINDING_SECTIONS):
        return result
    failures = candidate_binding_failures(r9, manifest, ledger, command, snapshot, b5_volume_min)
    for reason, refs in failures.items():
        for ref in refs:
            breaks.add(reason, "CANDIDATE_BINDING", ref)
        bound: bool | str = not refs
        if bound is True and reason == SNAPSHOT_BINDING_MISMATCH and ledger.exact_s is None:
            bound = NOT_EXECUTED  # the ledger's exact-S is missing evidence, never a pass
        result[reason.removesuffix("_MISMATCH")] = bound
    return result


def _safe_digest(value: Mapping[str, Any]) -> str | None:
    try:
        return evidence_digest(dict(value))
    except (TypeError, ValueError):
        return None


def iter_break_codes(report: Mapping[str, Any]) -> Iterable[str]:
    return (item["code"] for item in report.get("breaks", []))


__all__ = [
    "CHAIN_EVIDENCE_SCHEMA",
    "CHAIN_REPORT_SCHEMA",
    "NOT_EXECUTED",
    "EaLedgerRowV1",
    "RiskDecisionRefV1",
    "TradePlanRefV1",
    "iter_break_codes",
    "parse_ea_ledger_csv",
    "reconcile_chain",
]
