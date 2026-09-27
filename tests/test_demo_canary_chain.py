"""Offline chain reconciliation: TradePlan -> RiskDecision -> command -> EA receipt -> order -> deal -> position."""

from __future__ import annotations

import ast
import copy
import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from ops.demo_canary_verifier.__main__ import main
from ops.demo_canary_verifier.chain import (
    CHAIN_EVIDENCE_SCHEMA,
    NOT_EXECUTED,
    iter_break_codes,
    parse_ea_ledger_csv,
    reconcile_chain,
)
from ops.demo_canary_verifier.envelope import ENVELOPE_V1_SHA256, load_envelope
from ops.demo_canary_verifier.side_ledger import (
    NO_SUBMIT,
    SUBMIT_VOLUME_MIN,
    V31SideLedgerV1,
    bounded_canary_volume,
    evidence_decimal,
)
from ops.mt5_mcp.reconcile import _fingerprint
from tests.test_demo_canary_envelope import (
    ACCOUNT_ID,
    BROKER_SYMBOL,
    COMMAND_ID,
    EXECUTOR_ID,
    MAGIC,
    RISK_DECISION_ID,
    T0,
    TRADEPLAN_ID,
    command,
    iso,
    side_ledger,
    snapshot,
)

WINDOW_FROM = T0 - timedelta(minutes=1)
WINDOW_TO = T0 + timedelta(minutes=10)
COLLECTED = WINDOW_TO + timedelta(seconds=1)
ORDER, DEAL, POSITION = 5001, 6001, 7001
IN_WINDOW = T0 + timedelta(seconds=2)
SECOND_COMMAND_ID = "44444444-4444-4444-8444-444444444444"


def order_record(ticket: int = ORDER, *, position_id: int = POSITION, magic: int = MAGIC, state: int = 4) -> dict:
    return {
        "ticket": ticket,
        "time_setup_msc_utc": iso(IN_WINDOW),
        "type": 0,
        "state": state,
        "magic": magic,
        "position_id": position_id,
        "volume_initial": 0.01,
        "symbol": BROKER_SYMBOL,
    }


def deal_record(
    ticket: int = DEAL, *, order: int = ORDER, position_id: int = POSITION, entry: int = 0, magic: int = MAGIC
) -> dict:
    return {
        "ticket": ticket,
        "order": order,
        "time_msc_utc": iso(IN_WINDOW),
        "type": 0,
        "entry": entry,
        "magic": magic,
        "position_id": position_id,
        "volume": 0.01,
        "price": 1.1,
        "symbol": BROKER_SYMBOL,
    }


def position_record(identifier: int = POSITION, *, magic: int = MAGIC, volume: float = 0.01) -> dict:
    return {
        "ticket": identifier,
        "identifier": identifier,
        "time_msc_utc": iso(IN_WINDOW),
        "type": 0,
        "magic": magic,
        "volume": volume,
        "symbol": BROKER_SYMBOL,
    }


def tool(records: list[dict], *, history: bool = False) -> dict:
    payload: dict[str, Any] = {
        "measurement_state": "MEASURED" if records else "MEASURED_EMPTY",
        "truncated": False,
        "observed_at_utc": iso(COLLECTED),
        "records": records,
        "record_count": len(records),
        "source_record_count": len(records),
    }
    if history:
        payload["window"] = {"from_utc": iso(WINDOW_FROM), "to_utc": iso(WINDOW_TO)}
    return payload


def broker(
    *,
    account_mode: int = 0,
    orders: list[dict] | None = None,
    history_orders: list[dict] | None = None,
    deals: list[dict] | None = None,
    positions: list[dict] | None = None,
) -> dict:
    return {
        "tool_surface_exact": True,
        "window": {"from_utc": iso(WINDOW_FROM), "to_utc": iso(WINDOW_TO)},
        "collection_interval": {"started_at_utc": iso(COLLECTED), "finished_at_utc": iso(COLLECTED)},
        "snapshots": {
            "mt5_account_get": tool([{"trade_mode": account_mode}]),
            "mt5_orders_get": tool(orders or []),
            "mt5_history_orders_get": tool(
                [order_record()] if history_orders is None else history_orders, history=True
            ),
            "mt5_history_deals_get": tool([deal_record()] if deals is None else deals, history=True),
            "mt5_positions_get": tool([position_record()] if positions is None else positions),
        },
    }


def receipt(
    sequence: int,
    state: str,
    reason: str,
    *,
    command_id: str = COMMAND_ID,
    order_ticket: int | None = None,
    deal_ticket: int | None = None,
    position_id: int | None = None,
) -> dict:
    return {
        "event": "execution_report",
        "protocol_version": "wolf15.mt5.exec.v1",
        "report_id": f"00000000-0000-4000-8000-{sequence:012d}",
        "command_id": command_id,
        "idempotency_key": "demo-acct-01:5scr:plan-a:1:PLACE_MARKET",
        "sequence": sequence,
        "state": state,
        "event_time_utc": iso(IN_WINDOW),
        "executor_id": EXECUTOR_ID,
        "account_id": ACCOUNT_ID,
        "request_hash": "sha256:" + "d" * 64,
        "broker": {"order_ticket": order_ticket, "deal_ticket": deal_ticket, "position_id": position_id},
        "reason_code": reason,
    }


def filled_receipts() -> list[dict]:
    return [
        receipt(1, "SUBMITTING", "DEMO_ORDER_CHECK_PASSED"),
        receipt(
            2,
            "AMBIGUOUS_REQUIRES_RECONCILIATION",
            "DEMO_ONE_ORDER_FILL_REQUIRES_HISTORY_RECONCILIATION",
            order_ticket=ORDER,
            deal_ticket=DEAL,
        ),
    ]


def marker(command_id: str = COMMAND_ID, detail: str = "ATTEMPT_1_OF_1") -> dict:
    return {
        "timestamp_utc": iso(IN_WINDOW),
        "command_id": command_id,
        "state": "PERSIST_BEFORE_ORDERSEND",
        "detail": detail,
    }


FILL_REPORT_ID = "00000000-0000-4000-8000-000000000002"
BROKER_TRUTH = {
    "order_ref": _fingerprint("ORDER", ORDER),
    "deal_ref": _fingerprint("DEAL", DEAL),
    "position_ref": _fingerprint("POSITION", POSITION),
}


def chain_ledger(**overrides: Any) -> dict[str, Any]:
    return side_ledger(**{"ea_receipt_report_id": FILL_REPORT_ID, "broker_truth": dict(BROKER_TRUTH), **overrides})


def evidence(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": CHAIN_EVIDENCE_SCHEMA,
        "envelope_sha256": ENVELOPE_V1_SHA256,
        "window": {"from_utc": iso(WINDOW_FROM), "to_utc": iso(WINDOW_TO)},
        "tradeplans": [{"tradeplan_id": TRADEPLAN_ID, "tradeplan_revision": 3, "content_sha256": "sha256:" + "e" * 64}],
        "risk_decisions": [
            {
                "risk_decision_id": RISK_DECISION_ID,
                "tradeplan_id": TRADEPLAN_ID,
                "tradeplan_revision": 3,
                "decision": "APPROVED",
            }
        ],
        "commands": [command()],
        "ea_receipts": filled_receipts(),
        "ea_ledger": [{"timestamp_utc": iso(T0), "command_id": "-", "state": "STARTED", "detail": "x"}, marker()],
        "broker": broker(),
        "pinned_snapshot": snapshot(),
        "v31_side_ledger": chain_ledger(),
    }
    payload.update(overrides)
    return payload


def run(payload: dict[str, Any]) -> dict[str, Any]:
    return reconcile_chain(payload, envelope=load_envelope())


def codes(report: dict[str, Any]) -> set[str]:
    return set(iter_break_codes(report))


def test_fully_joined_chain_reconciles() -> None:
    report = run(evidence())
    assert report["breaks"] == []
    assert report["status"] == "RECONCILED"
    assert report["acceptance"] == {
        "ONE_COMMAND": True,
        "ONE_SUBMIT_MAX": True,
        "DUPLICATE_ORDER": 0,
        "UNKNOWN_POSITION": 0,
        "ORPHAN_ORDER": 0,
        "UNACCOUNTED_BROKER_FILL": 0,
        "V31_SIDE_LEDGER_JOINED": True,
        "V31_EXACT_S": "MEASURED",
        "BROKER_TRUTH_RECONCILED": True,
    }
    assert report["v31_side_ledger"]["status"] == "JOINED"
    assert report["v31_side_ledger"]["canonical_sized_volume"] == "0.03"
    assert report["v31_side_ledger"]["demo_submitted_volume"] == "0.01"
    assert report["v31_side_ledger"]["broker_volume_min"] == "0.01"
    assert report["v31_side_ledger"]["volume_decision"] == "SUBMIT_VOLUME_MIN"
    assert report["v31_side_ledger"]["volume_reason"] == "BOUNDED_CANARY_DOWNSIZE_TO_VOLUME_MIN"
    assert report["chains"] == [
        {
            "command_id": COMMAND_ID,
            "hops": {
                "TRADEPLAN": "JOINED",
                "RISK_DECISION": "JOINED",
                "COMMAND": "JOINED",
                "EA_RECEIPT": "JOINED",
                "MT5_ORDER": "JOINED",
                "DEAL": "JOINED",
                "POSITION": "JOINED",
            },
        }
    ]
    assert report["SUBMIT_AUTHORITY"] is False
    assert report["EXECUTION_READY"] is False


def test_protective_close_of_the_joined_position_still_reconciles() -> None:
    report = run(
        evidence(
            broker=broker(
                history_orders=[order_record(), order_record(5004, state=4)],
                deals=[deal_record(), deal_record(6004, order=5004, entry=1)],
                positions=[],
            )
        )
    )
    assert report["status"] == "RECONCILED", report["breaks"]


def test_broker_rejected_command_with_no_broker_effect_reconciles() -> None:
    report = run(
        evidence(
            ea_receipts=[
                receipt(1, "SUBMITTING", "DEMO_ORDER_CHECK_PASSED"),
                receipt(2, "BROKER_REJECTED", "DEMO_BROKER_REJECTED"),
            ],
            broker=broker(history_orders=[], deals=[], positions=[]),
            v31_side_ledger=chain_ledger(broker_truth=None),
        )
    )
    assert report["status"] == "RECONCILED", report["breaks"]
    assert report["chains"][0]["hops"]["MT5_ORDER"] == "ABSENT"


def test_report_never_contains_raw_broker_tickets() -> None:
    serialized = json.dumps(run(evidence(broker=broker(orders=[order_record(5999, magic=1)]))))
    assert "5999" not in serialized
    assert "5001" not in serialized


def test_two_commands_fail_one_command() -> None:
    second = command(command_id=SECOND_COMMAND_ID, idempotency_key="demo-acct-01:5scr:plan-a:2:PLACE_MARKET")
    report = run(evidence(commands=[command(), second]))
    assert report["acceptance"]["ONE_COMMAND"] is False
    assert report["acceptance"]["BROKER_TRUTH_RECONCILED"] is False
    assert {"NOT_ONE_COMMAND", "COMMAND_WITHOUT_EA_RECEIPT"} <= codes(report)


def test_duplicate_idempotency_key_counts_as_two_commands() -> None:
    report = run(evidence(commands=[command(), command(command_id=SECOND_COMMAND_ID)]))
    assert report["acceptance"]["ONE_COMMAND"] is False
    assert "DUPLICATE_IDEMPOTENCY_KEY" in codes(report)


@pytest.mark.parametrize(
    "ledger",
    [
        [marker(), marker()],
        [marker(detail="ATTEMPT_2_OF_2")],
    ],
)
def test_retry_fails_one_submit_max(ledger: list[dict]) -> None:
    report = run(evidence(ea_ledger=ledger))
    assert report["acceptance"]["ONE_SUBMIT_MAX"] is False
    assert report["acceptance"]["BROKER_TRUTH_RECONCILED"] is False
    assert "AUTO_RETRY_SUBMIT_OBSERVED" in codes(report)


def test_revised_command_is_a_retry() -> None:
    report = run(evidence(commands=[command(revision=2)]))
    assert "ENVELOPE_AUTO_RETRY_REVISION_PRESENT" in codes(report)
    assert report["status"] == "NOT_RECONCILED"


def test_second_submit_is_a_duplicate_order_with_unaccounted_fill() -> None:
    report = run(
        evidence(
            broker=broker(
                history_orders=[order_record(), order_record(5002, position_id=7002)],
                deals=[deal_record(), deal_record(6002, order=5002, position_id=7002)],
                positions=[position_record(), position_record(7002)],
            )
        )
    )
    acceptance = report["acceptance"]
    assert acceptance["DUPLICATE_ORDER"] == 1
    assert acceptance["UNACCOUNTED_BROKER_FILL"] == 1
    assert acceptance["UNKNOWN_POSITION"] == 1
    assert acceptance["ONE_SUBMIT_MAX"] is False
    assert acceptance["BROKER_TRUTH_RECONCILED"] is False


def test_receipt_reporting_two_orders_counts_a_duplicate() -> None:
    receipts = [*filled_receipts(), receipt(3, "BROKER_ACCEPTED", "DEMO_ONE_ORDER_ACCEPTED", order_ticket=5002)]
    report = run(
        evidence(ea_receipts=receipts, broker=broker(history_orders=[order_record(), order_record(5002, state=2)]))
    )
    assert report["acceptance"]["DUPLICATE_ORDER"] == 1
    assert report["acceptance"]["ONE_SUBMIT_MAX"] is False


def test_orphan_order_is_counted() -> None:
    report = run(evidence(broker=broker(orders=[order_record(5009, magic=424242, position_id=0, state=1)])))
    assert report["acceptance"]["ORPHAN_ORDER"] == 1
    assert report["acceptance"]["DUPLICATE_ORDER"] == 0
    assert report["acceptance"]["BROKER_TRUTH_RECONCILED"] is False


def test_unknown_position_is_counted() -> None:
    report = run(evidence(broker=broker(positions=[position_record(), position_record(7100, magic=0)])))
    assert report["acceptance"]["UNKNOWN_POSITION"] == 1
    assert report["acceptance"]["BROKER_TRUTH_RECONCILED"] is False


def test_fill_without_command_is_unaccounted() -> None:
    report = run(
        evidence(
            commands=[],
            ea_receipts=[],
            ea_ledger=[],
            broker=broker(
                history_orders=[order_record(5010, magic=0, position_id=7010)],
                deals=[deal_record(6010, order=5010, position_id=7010, magic=0)],
                positions=[position_record(7010, magic=0)],
            ),
        )
    )
    acceptance = report["acceptance"]
    assert acceptance["ONE_COMMAND"] is False
    assert acceptance["UNACCOUNTED_BROKER_FILL"] == 1
    assert acceptance["ORPHAN_ORDER"] == 1
    assert acceptance["UNKNOWN_POSITION"] == 1
    assert acceptance["BROKER_TRUTH_RECONCILED"] is False
    assert "APPROVED_RISK_DECISION_WITHOUT_COMMAND" in codes(report)


def test_receipt_for_unknown_command_is_a_break() -> None:
    receipts = [*filled_receipts(), receipt(1, "RECEIVED", "RECEIVED_OK", command_id=SECOND_COMMAND_ID)]
    assert "RECEIPT_WITHOUT_COMMAND" in codes(run(evidence(ea_receipts=receipts)))


def test_non_demo_broker_account_is_not_reconciled() -> None:
    report = run(evidence(broker=broker(account_mode=2)))
    assert "ACCOUNT_NOT_DEMO" in codes(report)
    assert report["acceptance"]["BROKER_TRUTH_RECONCILED"] is False


def test_non_demo_executor_command_is_not_reconciled() -> None:
    report = run(evidence(commands=[command(execution_mode="LIVE")]))
    assert "ENVELOPE_EXECUTOR_NOT_DEMO" in codes(report)
    assert report["status"] == "NOT_RECONCILED"


def test_missing_ea_final_preflight_evidence_is_a_break() -> None:
    receipts = [r for r in filled_receipts() if r["state"] != "SUBMITTING"]
    report = run(evidence(ea_receipts=receipts))
    assert "EA_FINAL_PREFLIGHT_UNEVIDENCED" in codes(report)
    assert report["acceptance"]["BROKER_TRUTH_RECONCILED"] is False


def test_broker_effect_after_final_preflight_reject_is_a_break() -> None:
    receipts = [*filled_receipts(), receipt(3, "PREFLIGHT_REJECTED", "DEMO_FINAL_PREFLIGHT_REJECTED")]
    assert "BROKER_EFFECT_AFTER_FINAL_PREFLIGHT_REJECT" in codes(run(evidence(ea_receipts=receipts)))


def test_broker_effect_without_ea_submit_marker_is_a_break() -> None:
    report = run(evidence(ea_ledger=[]))
    assert "BROKER_EFFECT_WITHOUT_SINGLE_EA_SUBMIT_MARKER" in codes(report)


def test_netting_pyramid_add_on_is_duplicate_and_oversized() -> None:
    report = run(
        evidence(
            broker=broker(
                history_orders=[order_record(), order_record(5003)],
                deals=[deal_record(), deal_record(6003, order=5003, entry=0)],
                positions=[position_record(volume=0.02)],
            )
        )
    )
    assert report["acceptance"]["DUPLICATE_ORDER"] == 1
    assert report["acceptance"]["UNACCOUNTED_BROKER_FILL"] == 1
    assert "POSITION_VOLUME_EXCEEDS_COMMAND" in codes(report)
    assert report["acceptance"]["BROKER_TRUTH_RECONCILED"] is False


def test_multiple_positions_for_one_command_is_a_break() -> None:
    receipts = [*filled_receipts(), receipt(3, "FILLED", "DEMO_FILLED", position_id=7002)]
    report = run(evidence(ea_receipts=receipts, broker=broker(positions=[position_record(), position_record(7002)])))
    assert "MULTIPLE_POSITIONS_FOR_COMMAND" in codes(report)
    assert report["acceptance"]["BROKER_TRUTH_RECONCILED"] is False


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"risk_decisions": []}, "RISK_DECISION_NOT_FOUND"),
        ({"tradeplans": []}, "TRADEPLAN_REVISION_NOT_FOUND"),
        (
            {
                "risk_decisions": [
                    {
                        "risk_decision_id": RISK_DECISION_ID,
                        "tradeplan_id": "5scr-plan:" + "f" * 32,
                        "tradeplan_revision": 3,
                        "decision": "APPROVED",
                    }
                ]
            },
            "RISK_DECISION_TRADEPLAN_MISMATCH",
        ),
    ],
)
def test_strategy_lineage_break_is_reported(overrides: dict[str, Any], code: str) -> None:
    report = run(evidence(**overrides))
    assert code in codes(report)
    assert report["acceptance"]["BROKER_TRUTH_RECONCILED"] is False


@pytest.mark.parametrize(
    "section",
    ["broker", "ea_ledger", "commands", "ea_receipts", "window", "tradeplans", "pinned_snapshot", "v31_side_ledger"],
)
def test_missing_evidence_is_not_executed_never_pass(section: str) -> None:
    payload = evidence()
    del payload[section]
    report = run(payload)
    assert report["status"] == NOT_EXECUTED
    assert section in report["missing_evidence"]
    assert report["acceptance"]["BROKER_TRUTH_RECONCILED"] is False
    if section in {"broker", "window"}:
        for name in ("DUPLICATE_ORDER", "UNKNOWN_POSITION", "ORPHAN_ORDER", "UNACCOUNTED_BROKER_FILL"):
            assert report["acceptance"][name] == NOT_EXECUTED
    if section in {"broker", "ea_ledger", "window"}:
        assert report["acceptance"]["ONE_SUBMIT_MAX"] == NOT_EXECUTED
    if section == "commands":
        assert report["acceptance"]["ONE_COMMAND"] == NOT_EXECUTED
    if section == "v31_side_ledger":
        assert report["acceptance"]["V31_SIDE_LEDGER_JOINED"] == NOT_EXECUTED
        assert report["acceptance"]["V31_EXACT_S"] == "NOT_MEASURED"
        assert report["v31_side_ledger"]["status"] == NOT_EXECUTED


def test_truncated_broker_measurement_is_not_executed() -> None:
    payload = evidence()
    payload["broker"]["snapshots"]["mt5_history_deals_get"]["truncated"] = True
    report = run(payload)
    assert report["status"] == NOT_EXECUTED
    assert "broker" in report["missing_evidence"]


def test_preexisting_history_outside_window_is_ignored() -> None:
    old = deal_record(6900, order=5900, position_id=7900, magic=0)
    old["time_msc_utc"] = iso(WINDOW_FROM - timedelta(days=1))
    report = run(evidence(broker=broker(deals=[deal_record(), old])))
    assert report["status"] == "RECONCILED", report["breaks"]
    assert report["counts"]["historical_preexisting"] == 1


def test_reconciler_never_mutates_evidence() -> None:
    payload = evidence()
    before = copy.deepcopy(payload)
    run(payload)
    assert payload == before


def _mcp_export_fields() -> dict[str, set[str]]:
    # Read the export tuples statically: importing ops.mt5_mcp.server needs psutil, which only the MCP venv has.
    tree = ast.parse(
        (Path(__file__).resolve().parents[1] / "ops" / "mt5_mcp" / "server.py").read_text(encoding="utf-8")
    )
    fields: dict[str, set[str]] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id.endswith("_FIELDS")
            and isinstance(node.value, ast.Tuple)
        ):
            fields[node.target.id] = {str(elt.value) for elt in node.value.elts if isinstance(elt, ast.Constant)}
    return fields


def test_mcp_export_carries_every_field_the_join_reads() -> None:
    fields = _mcp_export_fields()
    assert {"ticket", "state", "magic", "position_id", "symbol", "time_setup_msc", "volume_initial"} <= fields[
        "_ORDER_FIELDS"
    ]
    assert {"ticket", "order", "type", "entry", "magic", "position_id", "time_msc"} <= fields["_DEAL_FIELDS"]
    assert {"ticket", "identifier", "magic", "volume", "symbol"} <= fields["_POSITION_FIELDS"]
    assert "trade_mode" in fields["_ACCOUNT_FIELDS"]


def test_ea_ledger_csv_parser_matches_append_ledger_format() -> None:
    text = "2026.09.22 08:00:02;33333333-3333-4333-8333-333333333333;PERSIST_BEFORE_ORDERSEND;ATTEMPT_1_OF_1\r\n"
    assert parse_ea_ledger_csv(text) == [marker() | {"timestamp_utc": "2026.09.22 08:00:02"}]
    with pytest.raises(ValueError, match="EA_LEDGER_ROW_MALFORMED"):
        parse_ea_ledger_csv("only;three;fields\n")


def test_cli_writes_report_once_with_reused_exit_codes(tmp_path: Path) -> None:
    payload = evidence()
    ledger = payload.pop("ea_ledger")
    source = tmp_path / "chain.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    csv = tmp_path / "demo-ledger.csv"
    csv.write_bytes(
        "".join(f"{r['timestamp_utc']};{r['command_id']};{r['state']};{r['detail']}\n" for r in ledger).encode("utf-16")
    )
    out = tmp_path / "report.json"
    assert main(["reconcile", "--evidence", str(source), "--ea-ledger-csv", str(csv), "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["acceptance"]["BROKER_TRUTH_RECONCILED"] is True
    assert main(["reconcile", "--evidence", str(source), "--out", str(out)]) == 5  # never overwrites

    missing = tmp_path / "missing.json"
    missing.write_text(json.dumps(payload), encoding="utf-8")
    assert main(["reconcile", "--evidence", str(missing), "--out", str(tmp_path / "r2.json")]) == 2


def test_cli_envelope_mode_refuses_with_blocked_exit(tmp_path: Path) -> None:
    from tests.test_demo_canary_envelope import bundle

    source = tmp_path / "bundle.json"
    source.write_text(json.dumps(bundle(account={"trade_mode": 2})), encoding="utf-8")
    out = tmp_path / "decision.json"
    assert main(["envelope", "--bundle", str(source), "--out", str(out)]) == 3
    assert "ACCOUNT_NOT_DEMO" in json.loads(out.read_text(encoding="utf-8"))["refusals"]
    source.write_text(json.dumps(bundle()), encoding="utf-8")
    assert main(["envelope", "--bundle", str(source), "--out", str(tmp_path / "ok.json")]) == 0


# ---- B1: ENGINEERING_DEMO_CANARY + immutable V31 side ledger ----------------------------------------------------


def test_report_carries_the_fixed_claim_boundary() -> None:
    for report in (run(evidence()), run(evidence(v31_side_ledger=None))):
        assert report["PATH_LABEL"] == "ENGINEERING_DEMO_CANARY"
        assert report["EA_NATIVE_V31_SCORECARD"] == "NOT_PROVEN"
        assert report["PRODUCTION_READY"] is False
        assert report["claim_boundary"] == {
            "PATH_LABEL": "ENGINEERING_DEMO_CANARY",
            "EA_NATIVE_V31_SCORECARD": "NOT_PROVEN",
            "PRODUCTION_READY": False,
        }


def test_missing_side_ledger_is_not_executed_never_reconciled() -> None:
    report = run(evidence(v31_side_ledger=None))
    assert report["status"] == NOT_EXECUTED
    assert "v31_side_ledger" in report["missing_evidence"]
    assert report["acceptance"]["V31_SIDE_LEDGER_JOINED"] == NOT_EXECUTED
    assert report["acceptance"]["BROKER_TRUTH_RECONCILED"] is False


def test_missing_exact_s_is_not_measured_and_blocks_reconciliation() -> None:
    report = run(evidence(v31_side_ledger=chain_ledger(exact_s=None)))
    assert report["breaks"] == []
    assert report["acceptance"]["V31_EXACT_S"] == "NOT_MEASURED"
    assert report["acceptance"]["V31_SIDE_LEDGER_JOINED"] is True
    assert report["acceptance"]["BROKER_TRUTH_RECONCILED"] is False
    assert report["missing_evidence"] == ["v31_side_ledger.exact_s"]
    assert report["status"] == NOT_EXECUTED


@pytest.mark.parametrize(
    "exact_s",
    [
        {
            "source_artifact": "R8",
            "r9_artifact_sha256": "sha256:" + "9" * 64,
            "exact_s_id": "x-001",
            "exact_s_sha256": "sha256:" + "5" * 64,
        },
        {"source_artifact": "R9", "exact_s_id": "x-001", "exact_s_sha256": "sha256:" + "5" * 64},
        {
            "source_artifact": "R9",
            "r9_artifact_sha256": "sha256:" + "9" * 64,
            "exact_s_id": "x-001",
            "exact_s_sha256": "not-a-digest",
        },
    ],
)
def test_exact_s_not_from_an_r9_artifact_never_passes(exact_s: dict[str, Any]) -> None:
    report = run(evidence(v31_side_ledger=chain_ledger(exact_s=exact_s)))
    assert "V31_SIDE_LEDGER_INVALID" in codes(report)
    assert report["acceptance"]["V31_EXACT_S"] == "NOT_MEASURED"
    assert report["acceptance"]["BROKER_TRUTH_RECONCILED"] is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"path_label": "LIVE"},
        {"volume_reason": "UPSIZE"},
        {"extra_field": 1},
        {"canonical_sized_volume": True},
        {"demo_submitted_volume": "NaN"},
        {"demo_submitted_volume": 0},
    ],
)
def test_malformed_side_ledger_is_invalid(overrides: dict[str, Any]) -> None:
    report = run(evidence(v31_side_ledger=chain_ledger(**overrides)))
    assert "V31_SIDE_LEDGER_INVALID" in codes(report)
    assert report["v31_side_ledger"]["status"] == "INVALID"
    assert report["acceptance"]["BROKER_TRUTH_RECONCILED"] is False


def test_side_ledger_model_is_immutable() -> None:
    ledger = V31SideLedgerV1.model_validate(chain_ledger())
    with pytest.raises(ValueError):
        ledger.demo_submitted_volume = Decimal("1")


OTHER_REF = "0123456789abcdef"


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"command_id": SECOND_COMMAND_ID}, "V31_LEDGER_COMMAND_ID_MISMATCH"),
        ({"tradeplan_candidate_id": "5scr-plan:" + "f" * 32}, "V31_LEDGER_TRADEPLAN_MISMATCH"),
        ({"tradeplan_candidate_revision": 4}, "V31_LEDGER_TRADEPLAN_MISMATCH"),
        ({"risk_decision_id": "55555555-5555-4555-8555-555555555555"}, "V31_LEDGER_RISK_DECISION_MISMATCH"),
        ({"risk_reservation_id": "55555555-5555-4555-8555-555555555555"}, "V31_LEDGER_RISK_RESERVATION_MISMATCH"),
        ({"broker_adaptation_digest": "sha256:" + "0" * 64}, "V31_LEDGER_BROKER_ADAPTATION_DIGEST_MISMATCH"),
        ({"ea_receipt_report_id": None}, "V31_LEDGER_EA_RECEIPT_MISMATCH"),
        ({"ea_receipt_report_id": "00000000-0000-4000-8000-000000000099"}, "V31_LEDGER_EA_RECEIPT_MISMATCH"),
        ({"broker_truth": None}, "V31_LEDGER_BROKER_TRUTH_MISMATCH"),
        ({"broker_truth": {**BROKER_TRUTH, "order_ref": OTHER_REF}}, "V31_LEDGER_BROKER_TRUTH_MISMATCH"),
        ({"broker_truth": {**BROKER_TRUTH, "deal_ref": OTHER_REF}}, "V31_LEDGER_BROKER_TRUTH_MISMATCH"),
        ({"broker_truth": {**BROKER_TRUTH, "position_ref": OTHER_REF}}, "V31_LEDGER_BROKER_TRUTH_MISMATCH"),
    ],
)
def test_side_ledger_identifier_mismatch_is_a_break(overrides: dict[str, Any], code: str) -> None:
    report = run(evidence(v31_side_ledger=chain_ledger(**overrides)))
    assert code in codes(report)
    assert report["acceptance"]["V31_SIDE_LEDGER_JOINED"] is False
    assert report["v31_side_ledger"]["status"] == "BROKEN"
    assert report["acceptance"]["BROKER_TRUTH_RECONCILED"] is False
    assert report["status"] == "NOT_RECONCILED"


def test_ledger_risk_decision_must_be_the_one_the_command_carries() -> None:
    other = "55555555-5555-4555-8555-555555555555"
    decisions = [
        *evidence()["risk_decisions"],
        {"risk_decision_id": other, "tradeplan_id": TRADEPLAN_ID, "tradeplan_revision": 3, "decision": "REJECTED"},
    ]
    report = run(evidence(risk_decisions=decisions, v31_side_ledger=chain_ledger(risk_decision_id=other)))
    assert "V31_LEDGER_RISK_DECISION_MISMATCH" in codes(report)


def test_ledger_risk_decision_must_bind_the_ledger_tradeplan_revision() -> None:
    plans = [
        *evidence()["tradeplans"],
        {"tradeplan_id": TRADEPLAN_ID, "tradeplan_revision": 2, "content_sha256": "sha256:" + "e" * 64},
    ]
    decisions = [
        {
            "risk_decision_id": RISK_DECISION_ID,
            "tradeplan_id": TRADEPLAN_ID,
            "tradeplan_revision": 2,
            "decision": "APPROVED",
        }
    ]
    report = run(evidence(tradeplans=plans, risk_decisions=decisions))
    assert codes(report) == {"V31_LEDGER_RISK_DECISION_MISMATCH"}


def test_ledger_broker_truth_refs_with_two_joined_orders_are_a_break() -> None:
    receipts = [*filled_receipts(), receipt(3, "BROKER_ACCEPTED", "DEMO_ONE_ORDER_ACCEPTED", order_ticket=5002)]
    report = run(
        evidence(ea_receipts=receipts, broker=broker(history_orders=[order_record(), order_record(5002, state=2)]))
    )
    assert "V31_LEDGER_BROKER_TRUTH_MISMATCH" in codes(report)


def test_pinned_snapshot_must_bind_the_command() -> None:
    report = run(evidence(pinned_snapshot=snapshot(snapshot_id="other-snapshot")))
    assert codes(report) == {"PINNED_SNAPSHOT_BINDING_MISMATCH"}


def test_invalid_pinned_snapshot_is_a_break_and_has_no_volume_min() -> None:
    report = run(evidence(pinned_snapshot={"snapshot_id": "x"}))
    assert {"RECORD_INVALID", "BROKER_VOLUME_MIN_EVIDENCE_MISSING"} <= codes(report)
    assert report["acceptance"]["BROKER_TRUTH_RECONCILED"] is False


# ---- B5: bounded volume-min canary, never increase risk ---------------------------------------------------------


def test_bounded_canary_volume_decision() -> None:
    assert bounded_canary_volume(Decimal("0.009"), Decimal("0.01")) == (NO_SUBMIT, None)
    assert bounded_canary_volume(Decimal("0.01"), Decimal("0.01")) == (SUBMIT_VOLUME_MIN, Decimal("0.01"))
    assert bounded_canary_volume(Decimal("5"), Decimal("0.01")) == (SUBMIT_VOLUME_MIN, Decimal("0.01"))


def test_evidence_decimal_is_exact_and_never_rounds() -> None:
    assert evidence_decimal(0.1) == Decimal("0.1")
    assert str(evidence_decimal(0.1)) == "0.1"
    assert evidence_decimal("0.0100") == Decimal("0.01")
    assert str(evidence_decimal("0.0100")) == "0.0100"
    assert evidence_decimal(0.012345678901) == Decimal("0.012345678901")
    assert evidence_decimal(Decimal("0.02")) == Decimal("0.02")
    assert evidence_decimal(2) == Decimal("2")
    for bad in (True, None, "abc", float("nan"), float("inf"), "Infinity", [0.01]):
        assert evidence_decimal(bad) is None


def test_canonical_volume_below_broker_min_is_a_break() -> None:
    report = run(evidence(v31_side_ledger=chain_ledger(canonical_sized_volume="0.009")))
    assert {"CANONICAL_VOLUME_BELOW_BROKER_MIN", "DEMO_SUBMITTED_VOLUME_EXCEEDS_CANONICAL"} <= codes(report)
    assert report["v31_side_ledger"]["volume_decision"] == "NO_SUBMIT"
    assert report["acceptance"]["BROKER_TRUTH_RECONCILED"] is False


def test_canonical_volume_equal_to_broker_min_reconciles() -> None:
    report = run(evidence(v31_side_ledger=chain_ledger(canonical_sized_volume=0.01)))
    assert report["status"] == "RECONCILED", report["breaks"]


def test_upsized_demo_submission_is_a_break() -> None:
    upsized = command(volume=0.02)
    ledger = chain_ledger(for_command=upsized, demo_submitted_volume="0.02")
    history = [order_record() | {"volume_initial": 0.02}]
    report = run(evidence(commands=[upsized], v31_side_ledger=ledger, broker=broker(history_orders=history)))
    assert codes(report) == {"DEMO_SUBMITTED_VOLUME_EXCEEDS_VOLUME_MIN", "DEMO_SUBMITTED_VOLUME_NOT_VOLUME_MIN"}


def test_demo_submission_below_volume_min_is_a_break() -> None:
    small = command(volume=0.005)
    ledger = chain_ledger(for_command=small, demo_submitted_volume="0.005")
    history = [order_record() | {"volume_initial": 0.005}]
    positions = [position_record(volume=0.005)]
    report = run(
        evidence(commands=[small], v31_side_ledger=ledger, broker=broker(history_orders=history, positions=positions))
    )
    assert codes(report) == {"DEMO_SUBMITTED_VOLUME_NOT_VOLUME_MIN"}


def test_command_volume_differing_from_ledger_is_a_break() -> None:
    other = command(volume=0.02)
    report = run(evidence(commands=[other], v31_side_ledger=chain_ledger(for_command=other)))
    assert codes(report) == {"COMMAND_VOLUME_NOT_DEMO_SUBMITTED_VOLUME"}


@pytest.mark.parametrize("volume_initial", [0.02, None, "0.01x"])
def test_broker_truth_order_volume_must_equal_demo_submitted_volume(volume_initial: object) -> None:
    history = [order_record() | {"volume_initial": volume_initial}]
    report = run(evidence(broker=broker(history_orders=history)))
    assert codes(report) == {"BROKER_ORDER_VOLUME_NOT_DEMO_SUBMITTED_VOLUME"}


def test_volume_min_is_read_from_the_pinned_snapshot_not_a_constant() -> None:
    symbols = snapshot()["symbols"]
    symbols[0] = {**symbols[0], "volume_min": 0.1, "volume_step": 0.1}
    pinned = snapshot(symbols=symbols)
    minimum = command(volume=0.1)
    ledger = chain_ledger(for_command=minimum, canonical_sized_volume=0.25, demo_submitted_volume=0.1)
    history = [order_record() | {"volume_initial": 0.1}]
    report = run(
        evidence(
            commands=[minimum],
            pinned_snapshot=pinned,
            v31_side_ledger=ledger,
            broker=broker(history_orders=history, positions=[position_record(volume=0.1)]),
        )
    )
    assert report["status"] == "RECONCILED", report["breaks"]
    assert report["v31_side_ledger"]["broker_volume_min"] == "0.1"
    assert "DEMO_SUBMITTED_VOLUME_NOT_VOLUME_MIN" in codes(run(evidence(pinned_snapshot=pinned)))
    missing_symbol = run(evidence(pinned_snapshot=snapshot(symbols=[])))
    assert codes(missing_symbol) == {"BROKER_VOLUME_MIN_EVIDENCE_MISSING"}
    assert missing_symbol["v31_side_ledger"]["volume_decision"] is None
