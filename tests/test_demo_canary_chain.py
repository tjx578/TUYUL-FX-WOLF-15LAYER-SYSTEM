"""Offline chain reconciliation: TradePlan -> RiskDecision -> command -> EA receipt -> order -> deal -> position."""

from __future__ import annotations

import ast
import copy
import json
from datetime import timedelta
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
        "BROKER_TRUTH_RECONCILED": True,
    }
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


@pytest.mark.parametrize("section", ["broker", "ea_ledger", "commands", "ea_receipts", "window", "tradeplans"])
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
    assert {"ticket", "state", "magic", "position_id", "symbol", "time_setup_msc"} <= fields["_ORDER_FIELDS"]
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
