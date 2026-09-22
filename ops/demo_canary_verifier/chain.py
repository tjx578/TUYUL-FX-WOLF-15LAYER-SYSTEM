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

Missing evidence never passes: any absent section yields ``NOT_EXECUTED`` values and
``BROKER_TRUTH_RECONCILED = False``.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from contracts.mt5_execution_protocol import (
    CommandGuards,
    CommandSource,
    ExecutionCommandV1,
    ExecutionReportState,
    ExecutionReportV1,
)
from ops.demo_canary_verifier.envelope import CanaryEnvelopeV1, check_command_envelope, envelope_sha256
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
REQUIRED_SECTIONS: Final = ("window", "tradeplans", "risk_decisions", "commands", "ea_receipts", "ea_ledger", "broker")


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
    reconciled = not missing and not breaks.items and one_command is True and one_submit_max is True
    status = NOT_EXECUTED if missing else ("RECONCILED" if reconciled else "NOT_RECONCILED")
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
            "BROKER_TRUTH_RECONCILED": reconciled,
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
        "SUBMIT_AUTHORITY": False,
        "EXECUTION_READY": False,
        "PRODUCTION_READY": False,
    }


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
