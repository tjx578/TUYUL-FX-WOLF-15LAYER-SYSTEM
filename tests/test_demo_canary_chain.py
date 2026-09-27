"""Offline chain reconciliation: TradePlan -> RiskDecision -> command -> EA receipt -> order -> deal -> position."""

from __future__ import annotations

import ast
import base64
import copy
import hashlib
import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from contracts.mt5_execution_protocol import (
    ENGINEERING_DEMO_CANARY_MAGIC,
    AccountSnapshotV1,
    ExecutionCommandV1,
    MarginMode,
    ShadowAcceptanceGuards,
    ShadowAcceptanceSource,
)
from ops.demo_canary_verifier import side_ledger as side_ledger_module
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
    CANDIDATE_MANIFEST_SCHEMA,
    NO_SUBMIT,
    R9_ENVELOPE_DOC_PATH,
    R9_ENVELOPE_FROZEN_SCHEMA_SHA256,
    R9_ENVELOPE_STATUS,
    SUBMIT_VOLUME_MIN,
    BrokerTruthRefsV1,
    CandidateManifestV1,
    ExactSRefV1,
    V31SideLedgerV1,
    bounded_canary_volume,
    candidate_binding_failures,
    command_snapshot_ref,
    command_source_symbols,
    evidence_decimal,
    g6_readiness,
    parse_r9_envelope,
    r9_envelope_frozen_pin_holds,
)
from ops.mt5_mcp.reconcile import _fingerprint
from tests.test_demo_canary_envelope import (
    ACCOUNT_ID,
    BROKER_SYMBOL,
    COMMAND_ID,
    EXACT_S,
    EXACT_S_SNAPSHOT_SHA256,
    EXECUTOR_ID,
    MAGIC,
    R9_ARTIFACT,
    R9_ARTIFACT_B64,
    R9_ARTIFACT_SHA256,
    RISK_DECISION_ID,
    SNAPSHOT_ID,
    T0,
    TRADEPLAN_ID,
    command,
    iso,
    r9_envelope,
    side_ledger,
    snapshot,
)
from tests.test_r9_envelope_v1 import FROZEN_SCHEMA_SHA256

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
        "r9_envelope": r9_envelope(),
        "r9_artifact_b64": R9_ARTIFACT_B64,
        "candidate_manifest": candidate_manifest(),
    }
    payload.update(overrides)
    return payload


def candidate_manifest(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": CANDIDATE_MANIFEST_SCHEMA,
        "tradeplan_candidate_id": TRADEPLAN_ID,
        "tradeplan_candidate_revision": 3,
        "canonical_symbol": "EURUSD",
        "pinned_snapshot_id": SNAPSHOT_ID,
        "pinned_snapshot_sha256": EXACT_S_SNAPSHOT_SHA256,
    }
    payload.update(overrides)
    return payload


def run(payload: dict[str, Any]) -> dict[str, Any]:
    return reconcile_chain(payload, envelope=load_envelope())


def codes(report: dict[str, Any]) -> set[str]:
    return set(iter_break_codes(report))


def _break_triples(report: dict[str, Any]) -> set[tuple[str, str, str]]:
    return {(item["code"], item["hop"], item["ref"]) for item in report["breaks"]}


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
        "G6_READY": True,
        "G6_READY_REASON": "READY",
    }
    assert report["r9_envelope_status"] == "FROZEN"
    assert report["r9_exact_s"] == {
        "frozen_schema_sha256": FROZEN_SCHEMA_SHA256,
        "frozen_pin_holds": True,
        "verdict": {"exact_s_accepted": True, "failure_reasons": [], "artifact_bytes_verified": True},
    }
    assert report["PRODUCTION_READY"] is False
    assert report["EA_NATIVE_V31_SCORECARD"] == "NOT_PROVEN"
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
    [
        "broker",
        "ea_ledger",
        "commands",
        "ea_receipts",
        "window",
        "tradeplans",
        "pinned_snapshot",
        "v31_side_ledger",
        "r9_envelope",
        "r9_artifact_b64",
        "candidate_manifest",
    ],
)
def test_missing_evidence_is_not_executed_never_pass(section: str) -> None:
    payload = evidence()
    del payload[section]
    report = run(payload)
    assert report["status"] == NOT_EXECUTED
    assert section in report["missing_evidence"]
    assert report["acceptance"]["BROKER_TRUTH_RECONCILED"] is False
    assert report["acceptance"]["G6_READY"] is False
    if section in {"r9_envelope", "r9_artifact_b64"}:
        assert report["acceptance"]["V31_EXACT_S"] == "NOT_MEASURED"
        assert report["acceptance"]["G6_READY_REASON"] == "R9_EXACT_S_NOT_ACCEPTED"
        assert report["breaks"] == []
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
    envelope_file = tmp_path / "r9-envelope.json"
    envelope_file.write_text(json.dumps(payload.pop("r9_envelope")), encoding="utf-8")
    del payload["r9_artifact_b64"]
    artifact_file = tmp_path / "r9-artifact.bin"
    artifact_file.write_bytes(R9_ARTIFACT)
    source = tmp_path / "chain.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    csv = tmp_path / "demo-ledger.csv"
    csv.write_bytes(
        "".join(f"{r['timestamp_utc']};{r['command_id']};{r['state']};{r['detail']}\n" for r in ledger).encode("utf-16")
    )
    r9_args = ["--r9-envelope", str(envelope_file), "--r9-artifact", str(artifact_file)]
    out = tmp_path / "report.json"
    assert main(["reconcile", "--evidence", str(source), "--ea-ledger-csv", str(csv), *r9_args, "--out", str(out)]) == 0
    acceptance = json.loads(out.read_text(encoding="utf-8"))["acceptance"]
    assert acceptance["BROKER_TRUTH_RECONCILED"] is True
    assert acceptance["G6_READY"] is True
    assert main(["reconcile", "--evidence", str(source), "--out", str(out)]) == 5  # never overwrites

    # Without the R9 envelope or the R9 artifact bytes exact-S is not accepted: not executed, never G6.
    for index, partial in enumerate((r9_args[:2], r9_args[2:])):
        partial_out = tmp_path / f"partial-{index}.json"
        argv = [
            "reconcile",
            "--evidence",
            str(source),
            "--ea-ledger-csv",
            str(csv),
            *partial,
            "--out",
            str(partial_out),
        ]
        assert main(argv) == 2
        partial_acceptance = json.loads(partial_out.read_text(encoding="utf-8"))["acceptance"]
        assert partial_acceptance["BROKER_TRUTH_RECONCILED"] is False
        assert partial_acceptance["G6_READY"] is False

    # Wrong artifact bytes: the verifier rejects, so the chain is refused.
    wrong = tmp_path / "wrong-artifact.bin"
    wrong.write_bytes(R9_ARTIFACT + b" ")
    argv = ["reconcile", "--evidence", str(source), "--ea-ledger-csv", str(csv), "--r9-envelope", str(envelope_file)]
    assert main([*argv, "--r9-artifact", str(wrong), "--out", str(tmp_path / "wrong.json")]) == 3

    both = tmp_path / "both.json"
    both.write_text(json.dumps(evidence()), encoding="utf-8")
    for extra in (r9_args[:2], r9_args[2:]):
        assert main(["reconcile", "--evidence", str(both), *extra, "--out", str(tmp_path / "twice.json")]) == 5
    assert not (tmp_path / "twice.json").exists()

    missing = tmp_path / "missing.json"
    missing.write_text(json.dumps(payload), encoding="utf-8")
    assert main(["reconcile", "--evidence", str(missing), *r9_args, "--out", str(tmp_path / "r2.json")]) == 2


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


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _all_keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _all_keys(item)}
    return set()


def test_no_field_or_report_key_is_named_broker_adaptation_digest() -> None:
    fields = {name for model in (V31SideLedgerV1, ExactSRefV1, BrokerTruthRefsV1) for name in model.model_fields}
    assert "broker_adaptation_digest" not in fields
    assert "adapted_command_provenance_digest" in V31SideLedgerV1.model_fields
    assert not hasattr(side_ledger_module, "broker_adaptation_digest")
    assert "broker_adaptation_digest" not in side_ledger_module.__all__
    broken = run(evidence(v31_side_ledger=chain_ledger(adapted_command_provenance_digest="sha256:" + "0" * 64)))
    for report in (run(evidence()), run(evidence(v31_side_ledger=None)), broken):
        keys = _all_keys(report)
        assert not any("broker_adaptation" in key.lower() for key in keys)
        assert not any("BROKER_ADAPTATION" in code for code in codes(report))
    assert "V31_LEDGER_ADAPTED_COMMAND_PROVENANCE_MISMATCH" in codes(broken)
    assert (
        run(evidence(v31_side_ledger={**chain_ledger(), "broker_adaptation_digest": "sha256:" + "1" * 64}))[
            "v31_side_ledger"
        ]["status"]
        == "INVALID"
    )


# ---- R9EnvelopeV1 (owner FROZEN 2026-09-28): verifier-only exact-S and the G6 gate --------------------------------


def test_r9_envelope_status_is_frozen_and_pinned_to_the_owner_freeze_record() -> None:
    assert R9_ENVELOPE_STATUS == "FROZEN"
    assert R9_ENVELOPE_FROZEN_SCHEMA_SHA256 == FROZEN_SCHEMA_SHA256
    text = R9_ENVELOPE_DOC_PATH.read_text(encoding="utf-8")
    assert f"\nfrozen_schema_sha256           = {FROZEN_SCHEMA_SHA256}\n" in text
    assert "\nenvelope_status                = FROZEN\n" in text
    assert r9_envelope_frozen_pin_holds() is True
    assert r9_envelope_frozen_pin_holds(R9_ENVELOPE_DOC_PATH) is True


def _doc_variant(tmp_path: Path, old: bytes, new: bytes) -> Path:
    raw = R9_ENVELOPE_DOC_PATH.read_bytes()
    assert raw.count(old) >= 1, old
    path = tmp_path / "r9-envelope-v1.md"
    path.write_bytes(raw.replace(old, new, 1))
    return path


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (b"envelope_status                = FROZEN", b"envelope_status                = DRAFT"),
        (b"frozen_schema_sha256           = 10732eeb", b"frozen_schema_sha256           = 00000000"),
        (b"frozen_schema_sha256           = ", b"frozen_schema_sha256_old       = "),
        (b"## 2.", b"## 2 ."),  # sections 1-7 differ from the frozen normative span
        (b"## 1. Purpose", b"## 1. Scope"),  # span anchor missing
        (b"\n## 8. Freeze record", b"\n## 8. Record"),  # span anchor missing
    ],
)
def test_frozen_pin_fails_closed_on_a_changed_schema_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, old: bytes, new: bytes
) -> None:
    variant = _doc_variant(tmp_path, old, new)
    assert r9_envelope_frozen_pin_holds(variant) is False
    monkeypatch.setattr(side_ledger_module, "R9_ENVELOPE_DOC_PATH", variant)
    report = run(evidence())
    assert report["acceptance"]["BROKER_TRUTH_RECONCILED"] is True
    assert report["r9_exact_s"]["frozen_pin_holds"] is False
    assert report["acceptance"]["G6_READY"] is False
    assert report["acceptance"]["G6_READY_REASON"] == "R9_ENVELOPE_FROZEN_PIN_MISMATCH"


@pytest.mark.parametrize("content", [None, b"\xff\xfe not utf-8 \xff"])
def test_frozen_pin_fails_closed_on_missing_or_unreadable_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: bytes | None
) -> None:
    path = tmp_path / "r9-envelope-v1.md"
    if content is not None:
        path.write_bytes(content)
    assert r9_envelope_frozen_pin_holds(path) is False
    monkeypatch.setattr(side_ledger_module, "R9_ENVELOPE_DOC_PATH", path)
    report = run(evidence())
    assert report["acceptance"]["G6_READY"] is False
    assert report["acceptance"]["G6_READY_REASON"] == "R9_ENVELOPE_FROZEN_PIN_MISMATCH"


@pytest.mark.parametrize(
    ("status", "pin", "accepted", "bound", "reconciled", "expected"),
    [
        ("FROZEN", True, True, (True, True, True), True, (True, "READY")),
        ("NOT_FROZEN", True, True, (True, True, True), True, (False, "R9_ENVELOPE_NOT_FROZEN")),
        ("", True, True, (True, True, True), True, (False, "R9_ENVELOPE_STATUS_UNRECOGNIZED")),
        ("frozen", True, True, (True, True, True), True, (False, "R9_ENVELOPE_STATUS_UNRECOGNIZED")),
        ("FROZEN", False, True, (True, True, True), True, (False, "R9_ENVELOPE_FROZEN_PIN_MISMATCH")),
        ("FROZEN", True, False, (True, True, True), True, (False, "R9_EXACT_S_NOT_ACCEPTED")),
        ("FROZEN", True, True, (False, True, True), True, (False, "SNAPSHOT_BINDING_MISMATCH")),
        ("FROZEN", True, True, (True, False, True), True, (False, "CAPABILITY_BINDING_MISMATCH")),
        ("FROZEN", True, True, (True, True, False), True, (False, "SYMBOL_CAPABILITY_BINDING_MISMATCH")),
        ("FROZEN", True, True, (False, False, False), False, (False, "SNAPSHOT_BINDING_MISMATCH")),
        ("FROZEN", True, True, (True, False, False), False, (False, "CAPABILITY_BINDING_MISMATCH")),
        ("FROZEN", True, True, (True, True, "NOT_EXECUTED"), True, (False, "SYMBOL_CAPABILITY_BINDING_MISMATCH")),
        ("FROZEN", True, True, (True, True, True), False, (False, "BROKER_TRUTH_NOT_RECONCILED")),
        ("FROZEN", False, False, (False, False, False), False, (False, "R9_ENVELOPE_FROZEN_PIN_MISMATCH")),
        ("FROZEN", True, False, (False, False, False), False, (False, "R9_EXACT_S_NOT_ACCEPTED")),
    ],
)
def test_g6_readiness_requires_frozen_pin_verdict_d3_bindings_and_broker_truth(
    status: str, pin: bool, accepted: bool, bound: tuple[Any, Any, Any], reconciled: bool, expected: tuple[bool, str]
) -> None:
    result = g6_readiness(
        status,
        frozen_pin_holds=pin,
        exact_s_accepted=accepted,
        snapshot_bound=bound[0],
        capability_bound=bound[1],
        symbol_bound=bound[2],
        broker_truth_reconciled=reconciled,
    )
    assert result == expected


def test_missing_r9_artifact_bytes_are_not_executed_and_never_g6() -> None:
    report = run(evidence(r9_artifact_b64=None))
    assert report["status"] == NOT_EXECUTED
    assert report["missing_evidence"] == ["r9_artifact_b64"]
    assert report["breaks"] == []
    assert report["r9_exact_s"]["verdict"] == {
        "exact_s_accepted": False,
        "failure_reasons": ["ARTIFACT_BYTES_REQUIRED"],
        "artifact_bytes_verified": False,
    }
    assert report["acceptance"]["V31_EXACT_S"] == "NOT_MEASURED"
    assert report["acceptance"]["BROKER_TRUTH_RECONCILED"] is False
    assert (report["acceptance"]["G6_READY"], report["acceptance"]["G6_READY_REASON"]) == (
        False,
        "R9_EXACT_S_NOT_ACCEPTED",
    )


def test_missing_r9_envelope_has_no_verdict_and_hash_only_exact_s_never_passes() -> None:
    """The ledger's exact-S alone (R9 label + hashes, the old hash-only basis) is never accepted."""

    report = run(evidence(r9_envelope=None))
    assert report["missing_evidence"] == ["r9_envelope"]
    assert report["r9_exact_s"]["verdict"] is None
    assert report["acceptance"]["V31_EXACT_S"] == "NOT_MEASURED"
    assert report["acceptance"]["BROKER_TRUTH_RECONCILED"] is False
    assert report["acceptance"]["G6_READY"] is False


@pytest.mark.parametrize(
    "artifact_b64",
    [
        base64.b64encode(R9_ARTIFACT + b" ").decode("ascii"),
        base64.b64encode(b"").decode("ascii"),
        base64.b64encode(R9_ARTIFACT_SHA256.encode("ascii")).decode("ascii"),  # the hash is not the artifact
    ],
)
def test_wrong_r9_artifact_bytes_are_rejected_by_the_verifier(artifact_b64: str) -> None:
    report = run(evidence(r9_artifact_b64=artifact_b64))
    assert codes(report) == {"R9_EXACT_S_NOT_ACCEPTED"}
    assert report["breaks"] == [
        {"code": "R9_EXACT_S_NOT_ACCEPTED", "hop": "R9_ENVELOPE", "ref": "ARTIFACT_SHA256_MISMATCH"}
    ]
    assert report["status"] == "NOT_RECONCILED"
    assert report["acceptance"]["V31_EXACT_S"] == "NOT_MEASURED"
    assert report["acceptance"]["BROKER_TRUTH_RECONCILED"] is False
    assert report["acceptance"]["G6_READY"] is False
    assert report["acceptance"]["G6_READY_REASON"] == "R9_EXACT_S_NOT_ACCEPTED"


@pytest.mark.parametrize("artifact_b64", ["!" + R9_ARTIFACT_B64, R9_ARTIFACT_B64[:-1], 12, ["x"], "é"])
def test_malformed_r9_artifact_encoding_is_a_break(artifact_b64: object) -> None:
    report = run(evidence(r9_artifact_b64=artifact_b64))
    assert {"R9_ARTIFACT_BYTES_INVALID", "R9_EXACT_S_NOT_ACCEPTED"} == codes(report)
    assert report["r9_exact_s"]["verdict"]["failure_reasons"] == ["ARTIFACT_BYTES_REQUIRED"]
    assert report["acceptance"]["V31_EXACT_S"] == "NOT_MEASURED"
    assert report["acceptance"]["BROKER_TRUTH_RECONCILED"] is False
    assert report["acceptance"]["G6_READY"] is False


def _with(section: str, **fields: Any) -> dict[str, Any]:
    envelope = r9_envelope()
    envelope[section] = {**envelope[section], **fields}
    return envelope


@pytest.mark.parametrize(
    ("envelope", "reason"),
    [
        (_with("active_readback", status="REVOKED"), "ACTIVE_READBACK_STATUS_NOT_ACTIVE"),
        (_with("capability", status="NOT_MEASURED"), "CAPABILITY_STATUS_NOT_MEASURED"),
        (_with("import", evidence_id="5a46f1fd-54e3-4241-9c03-8e0fa385a02d"), "IMPORT_EVIDENCE_ID_MISMATCH"),
        (r9_envelope(source_artifact="R8"), "SOURCE_ARTIFACT_NOT_R9"),
        ({**r9_envelope(), "exact_s_accepted": True}, "EXACT_S_ACCEPTED_SUPPLIED_BY_INPUT"),
        (r9_envelope(schema_version="v2"), "ENVELOPE_SCHEMA_INVALID"),
        (["not", "a", "mapping"], "ENVELOPE_SCHEMA_INVALID"),
    ],
)
def test_r9_verdict_rejection_blocks_exact_s(envelope: Any, reason: str) -> None:
    report = run(evidence(r9_envelope=envelope))
    assert ("R9_EXACT_S_NOT_ACCEPTED", "R9_ENVELOPE", reason) in {
        (item["code"], item["hop"], item["ref"]) for item in report["breaks"]
    }
    assert report["r9_exact_s"]["verdict"]["exact_s_accepted"] is False
    assert report["acceptance"]["V31_EXACT_S"] == "NOT_MEASURED"
    assert report["acceptance"]["BROKER_TRUTH_RECONCILED"] is False
    assert report["status"] == "NOT_RECONCILED"
    assert report["acceptance"]["G6_READY"] is False
    assert report["acceptance"]["G6_READY_REASON"] == "R9_EXACT_S_NOT_ACCEPTED"


@pytest.mark.parametrize(
    ("field", "value", "expected_codes", "reason"),
    [
        (
            "exact_s_id",
            "snapshot-other-002",
            {"V31_LEDGER_EXACT_S_ID_MISMATCH", "SNAPSHOT_BINDING_MISMATCH"},
            "SNAPSHOT_BINDING_MISMATCH",
        ),
        (
            "exact_s_sha256",
            "6" * 64,
            {"V31_LEDGER_EXACT_S_SHA256_MISMATCH", "SNAPSHOT_BINDING_MISMATCH"},
            "SNAPSHOT_BINDING_MISMATCH",
        ),
        ("r9_artifact_sha256", "9" * 64, {"V31_LEDGER_R9_ARTIFACT_SHA256_MISMATCH"}, "BROKER_TRUTH_NOT_RECONCILED"),
    ],
)
def test_ledger_exact_s_must_be_the_accepted_envelope_s(
    field: str, value: str, expected_codes: set[str], reason: str
) -> None:
    report = run(evidence(v31_side_ledger=chain_ledger(exact_s={**EXACT_S, field: value})))
    assert report["r9_exact_s"]["verdict"]["exact_s_accepted"] is True
    assert codes(report) == expected_codes
    assert report["v31_side_ledger"]["status"] == "BROKEN"
    assert report["acceptance"]["V31_EXACT_S"] == "NOT_MEASURED"
    assert report["acceptance"]["BROKER_TRUTH_RECONCILED"] is False
    assert report["status"] == "NOT_RECONCILED"
    assert (report["acceptance"]["G6_READY"], report["acceptance"]["G6_READY_REASON"]) == (False, reason)


def test_exact_s_binding_is_checked_even_when_the_verdict_rejects() -> None:
    ledger = chain_ledger(exact_s={**EXACT_S, "exact_s_id": "snapshot-other-002"})
    report = run(evidence(v31_side_ledger=ledger, r9_artifact_b64=base64.b64encode(b"x").decode("ascii")))
    assert {"R9_EXACT_S_NOT_ACCEPTED", "V31_LEDGER_EXACT_S_ID_MISMATCH", "SNAPSHOT_BINDING_MISMATCH"} == codes(report)


def test_a_different_consistent_r9_artifact_is_accepted_by_its_own_bytes() -> None:
    """Acceptance follows the verifier over the supplied bytes, not a hard-coded artifact."""

    artifact = b'{"run_id":"C2_RECONCILIATION_R9","attempt":2}\n'
    digest = hashlib.sha256(artifact).hexdigest()
    report = run(
        evidence(
            r9_envelope=r9_envelope(artifact_sha256=digest),
            r9_artifact_b64=base64.b64encode(artifact).decode("ascii"),
            v31_side_ledger=chain_ledger(exact_s={**EXACT_S, "r9_artifact_sha256": digest}),
        )
    )
    assert report["status"] == "RECONCILED", report["breaks"]
    assert report["acceptance"]["G6_READY"] is True
    assert EXACT_S["exact_s_id"] == SNAPSHOT_ID


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
        {**EXACT_S, "source_artifact": "R8"},
        {key: value for key, value in EXACT_S.items() if key != "r9_artifact_sha256"},
        {**EXACT_S, "exact_s_sha256": "not-a-digest"},
        # The frozen R9EnvelopeV1 sha256 format is reused exactly: no "sha256:" prefix, lowercase hex only.
        {**EXACT_S, "exact_s_sha256": "sha256:" + EXACT_S["exact_s_sha256"]},
        {**EXACT_S, "r9_artifact_sha256": "sha256:" + EXACT_S["r9_artifact_sha256"]},
        {**EXACT_S, "r9_artifact_sha256": EXACT_S["r9_artifact_sha256"].upper()},
        {**EXACT_S, "exact_s_id": "S"},
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
        ({"adapted_command_provenance_digest": "sha256:" + "0" * 64}, "V31_LEDGER_ADAPTED_COMMAND_PROVENANCE_MISMATCH"),
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
    assert codes(report) == {"PINNED_SNAPSHOT_BINDING_MISMATCH", "SNAPSHOT_BINDING_MISMATCH"}
    assert ("SNAPSHOT_BINDING_MISMATCH", "CANDIDATE_BINDING", "pinned_snapshot.snapshot_id") in _break_triples(report)


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
            r9_envelope=_with("capability", volume_min=0.1, volume_step=0.1),
        )
    )
    assert report["status"] == "RECONCILED", report["breaks"]
    assert report["v31_side_ledger"]["broker_volume_min"] == "0.1"
    assert "DEMO_SUBMITTED_VOLUME_NOT_VOLUME_MIN" in codes(run(evidence(pinned_snapshot=pinned)))
    missing_symbol = run(evidence(pinned_snapshot=snapshot(symbols=[])))
    assert codes(missing_symbol) == {"BROKER_VOLUME_MIN_EVIDENCE_MISSING", "CAPABILITY_BINDING_MISMATCH"}
    assert missing_symbol["v31_side_ledger"]["volume_decision"] is None


# ---- Owner D3 (2026-09-28): S, capability and symbol bindings are REQUIRED before G6_READY ------------------------

BOUND_S = {"snapshot_id": SNAPSHOT_ID, "snapshot_sha256": EXACT_S_SNAPSHOT_SHA256}
ALL_BOUND = {
    "SNAPSHOT_BINDING": True,
    "CAPABILITY_BINDING": True,
    "SYMBOL_CAPABILITY_BINDING": True,
    "bound_snapshot_s": BOUND_S,
}
OTHER_S_ID = "snapshot-other-002"


def _g6(report: dict[str, Any]) -> tuple[bool, str]:
    return report["acceptance"]["G6_READY"], report["acceptance"]["G6_READY_REASON"]


def _assert_d3_break(report: dict[str, Any], reason: str, refs: set[str]) -> None:
    assert {ref for code, hop, ref in _break_triples(report) if code == reason and hop == "CANDIDATE_BINDING"} == refs
    assert report["candidate_binding"][reason.removesuffix("_MISMATCH")] is False
    assert report["status"] == "NOT_RECONCILED"
    assert report["acceptance"]["BROKER_TRUTH_RECONCILED"] is False
    assert _g6(report) == (False, reason)
    assert report["runtime_candidate_binding"]["G6_READY_FOR_DEMO"] is False


def _command_with_snapshot_id(snapshot_id: str) -> dict[str, Any]:
    payload = command()
    payload["guards"]["risk_snapshot_id"] = snapshot_id
    return payload


def _r9_with_s(snapshot_id: str, snapshot_sha256: str) -> dict[str, Any]:
    identity = {"snapshot_id": snapshot_id, "snapshot_sha256": snapshot_sha256}
    envelope = r9_envelope(snapshot_s=dict(identity))
    envelope["collect"] = {**envelope["collect"], "attested_snapshot_identity": dict(identity)}
    envelope["import"] = {**envelope["import"], "imported_snapshot_identity": dict(identity)}
    envelope["active_readback"] = {**envelope["active_readback"], "readback_snapshot_identity": dict(identity)}
    envelope["capability"] = {**envelope["capability"], "snapshot_id": snapshot_id}
    envelope["direct_receipt"] = {**envelope["direct_receipt"], "snapshot_id": snapshot_id}
    return envelope


def test_d3_all_bindings_consistent_is_g6_ready() -> None:
    report = run(evidence())
    assert report["candidate_binding"] == ALL_BOUND
    assert report["status"] == "RECONCILED"
    assert _g6(report) == (True, "READY")


@pytest.mark.parametrize(
    ("overrides", "refs", "other_codes"),
    [
        (
            {"candidate_manifest": candidate_manifest(pinned_snapshot_id=OTHER_S_ID)},
            {"candidate_manifest.pinned_snapshot_id"},
            set(),
        ),
        (
            {"candidate_manifest": candidate_manifest(pinned_snapshot_sha256="6" * 64)},
            {"candidate_manifest.pinned_snapshot_sha256"},
            set(),
        ),
        (
            {"v31_side_ledger": chain_ledger(exact_s={**EXACT_S, "exact_s_id": OTHER_S_ID})},
            {"v31_side_ledger.exact_s.exact_s_id"},
            {"V31_LEDGER_EXACT_S_ID_MISMATCH"},
        ),
        (
            {"v31_side_ledger": chain_ledger(exact_s={**EXACT_S, "exact_s_sha256": "6" * 64})},
            {"v31_side_ledger.exact_s.exact_s_sha256"},
            {"V31_LEDGER_EXACT_S_SHA256_MISMATCH"},
        ),
        (
            {
                "commands": [_command_with_snapshot_id(OTHER_S_ID)],
                "v31_side_ledger": chain_ledger(for_command=_command_with_snapshot_id(OTHER_S_ID)),
            },
            {"command.guards.risk_snapshot_id"},
            {"PINNED_SNAPSHOT_BINDING_MISMATCH"},
        ),
        (
            {"pinned_snapshot": snapshot(snapshot_id=OTHER_S_ID)},
            {"pinned_snapshot.snapshot_id"},
            {"PINNED_SNAPSHOT_BINDING_MISMATCH"},
        ),
        (
            # A different, internally consistent (verifier-accepted) R9 S binds nothing else in the lineage.
            {"r9_envelope": _r9_with_s(OTHER_S_ID, "6" * 64)},
            {
                "candidate_manifest.pinned_snapshot_id",
                "candidate_manifest.pinned_snapshot_sha256",
                "command.guards.risk_snapshot_id",
                "pinned_snapshot.snapshot_id",
                "v31_side_ledger.exact_s.exact_s_id",
                "v31_side_ledger.exact_s.exact_s_sha256",
            },
            {"V31_LEDGER_EXACT_S_ID_MISMATCH", "V31_LEDGER_EXACT_S_SHA256_MISMATCH"},
        ),
    ],
)
def test_d3a_each_snapshot_link_mismatch_blocks_g6(
    overrides: dict[str, Any], refs: set[str], other_codes: set[str]
) -> None:
    report = run(evidence(**overrides))
    assert report["r9_exact_s"]["verdict"]["exact_s_accepted"] is True
    assert codes(report) == {"SNAPSHOT_BINDING_MISMATCH", *other_codes}
    _assert_d3_break(report, "SNAPSHOT_BINDING_MISMATCH", refs)


def test_d3a_bound_s_is_the_r9_s_and_a_latest_snapshot_s_plus_1_never_replaces_it() -> None:
    """#483: S is the immutable command/reconciliation lineage; a newer latest S+1 is veto authority only."""

    symbols = snapshot()["symbols"]
    latest = snapshot(
        snapshot_id="snapshot-latest-002",
        captured=T0 + timedelta(seconds=5),
        symbols=[{**symbols[0], "volume_min": 0.02, "volume_step": 0.02}],
    )
    baseline = run(evidence())
    report = run(evidence(latest_snapshot=latest))
    assert report["candidate_binding"] == ALL_BOUND
    assert report["candidate_binding"]["bound_snapshot_s"]["snapshot_id"] == SNAPSHOT_ID
    assert report["v31_side_ledger"]["broker_volume_min"] == "0.01"
    assert _g6(report) == (True, "READY")
    assert {**report, "evidence_sha256": None} == {**baseline, "evidence_sha256": None}
    # Substituting S+1 as the pinned snapshot never re-binds S: it is a snapshot binding break.
    swapped = run(evidence(pinned_snapshot=latest))
    assert "SNAPSHOT_BINDING_MISMATCH" in codes(swapped)
    assert swapped["candidate_binding"]["bound_snapshot_s"] == BOUND_S
    assert _g6(swapped) == (False, "SNAPSHOT_BINDING_MISMATCH")


def _capability_evidence(*, r9_min: Any, r9_step: Any, pinned_min: float = 0.1, pinned_step: float = 0.1) -> dict:
    symbols = snapshot()["symbols"]
    pinned = snapshot(symbols=[{**symbols[0], "volume_min": pinned_min, "volume_step": pinned_step}])
    minimum = command(volume=0.1)
    return evidence(
        commands=[minimum],
        pinned_snapshot=pinned,
        v31_side_ledger=chain_ledger(for_command=minimum, canonical_sized_volume="0.3", demo_submitted_volume="0.1"),
        broker=broker(
            history_orders=[order_record() | {"volume_initial": 0.1}], positions=[position_record(volume=0.1)]
        ),
        r9_envelope=_with("capability", volume_min=r9_min, volume_step=r9_step),
    )


@pytest.mark.parametrize(
    ("r9_min", "r9_step"),
    [(0.1, 0.1), (Decimal("0.1"), Decimal("0.1")), ("0.10", "0.100")],
)
def test_d3b_capability_binding_compares_exact_decimal_of_str(r9_min: Any, r9_step: Any) -> None:
    """0.1 (binary float) and Decimal("0.1") bind: both compare as Decimal(str(x)) == Decimal("0.1")."""

    report = run(_capability_evidence(r9_min=r9_min, r9_step=r9_step))
    assert report["status"] == "RECONCILED", report["breaks"]
    assert report["candidate_binding"]["CAPABILITY_BINDING"] is True
    assert _g6(report) == (True, "READY")


@pytest.mark.parametrize(
    ("kwargs", "refs", "other_codes"),
    [
        ({"r9_min": 0.2, "r9_step": 0.1}, {"pinned_snapshot.symbols.volume_min", "b5.volume_min"}, set()),
        (
            {"r9_min": 0.10000000000000002, "r9_step": 0.1},
            {"pinned_snapshot.symbols.volume_min", "b5.volume_min"},
            set(),
        ),
        ({"r9_min": 0.1, "r9_step": 0.2}, {"pinned_snapshot.symbols.volume_step"}, set()),
        ({"r9_min": 0.1, "r9_step": 0.1 + 0.2 - 0.2}, {"pinned_snapshot.symbols.volume_step"}, set()),
        ({"r9_min": 0.1, "r9_step": 0.1, "pinned_step": 0.05}, {"pinned_snapshot.symbols.volume_step"}, set()),
        (
            {"r9_min": 0.1, "r9_step": 0.1, "pinned_min": 0.05},
            {"pinned_snapshot.symbols.volume_min", "b5.volume_min"},
            {"DEMO_SUBMITTED_VOLUME_EXCEEDS_VOLUME_MIN", "DEMO_SUBMITTED_VOLUME_NOT_VOLUME_MIN"},
        ),
    ],
)
def test_d3b_each_capability_link_mismatch_blocks_g6(
    kwargs: dict[str, Any], refs: set[str], other_codes: set[str]
) -> None:
    report = run(_capability_evidence(**kwargs))
    assert report["r9_exact_s"]["verdict"]["exact_s_accepted"] is True
    assert codes(report) == {"CAPABILITY_BINDING_MISMATCH", *other_codes}
    _assert_d3_break(report, "CAPABILITY_BINDING_MISMATCH", refs)


def _order_symbols(canonical: str, broker_symbol: str) -> dict[str, Any]:
    symbols = snapshot()["symbols"]
    payload = command()
    payload["order"] = {**payload["order"], "canonical_symbol": canonical, "broker_symbol": broker_symbol}
    return {
        "commands": [payload],
        "v31_side_ledger": chain_ledger(for_command=payload),
        "pinned_snapshot": snapshot(
            symbols=[{**symbols[0], "canonical_symbol": canonical, "broker_symbol": broker_symbol}]
        ),
    }


@pytest.mark.parametrize(
    ("overrides", "refs"),
    [
        (
            {"candidate_manifest": candidate_manifest(canonical_symbol="GBPUSD")},
            {"candidate_manifest.canonical_symbol"},
        ),
        (
            {"r9_envelope": _with("capability", canonical_symbol="GBPUSD")},
            {"candidate_manifest.canonical_symbol", "command.order.canonical_symbol"},
        ),
        ({"r9_envelope": _with("capability", broker_symbol="EURUSD.b")}, {"command.order.broker_symbol"}),
        (_order_symbols("GBPUSD", BROKER_SYMBOL), {"command.order.canonical_symbol"}),
        (_order_symbols("EURUSD", "EURUSD.b"), {"command.order.broker_symbol"}),
    ],
)
def test_d3c_each_symbol_link_mismatch_blocks_g6(overrides: dict[str, Any], refs: set[str]) -> None:
    report = run(evidence(**overrides))
    assert report["r9_exact_s"]["verdict"]["exact_s_accepted"] is True
    assert codes(report) == {"SYMBOL_CAPABILITY_BINDING_MISMATCH"}
    _assert_d3_break(report, "SYMBOL_CAPABILITY_BINDING_MISMATCH", refs)


def _parsed(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "r9_envelope": parse_r9_envelope(r9_envelope()),
        "manifest": CandidateManifestV1.model_validate(candidate_manifest()),
        "ledger": V31SideLedgerV1.model_validate(chain_ledger()),
        "command": ExecutionCommandV1.model_validate(command()),
        "snapshot": AccountSnapshotV1.model_validate(snapshot()),
        "b5_volume_min": Decimal("0.01"),
    }
    values.update(overrides)
    return values


def _canary_command() -> ExecutionCommandV1:
    payload = command()
    payload["source"] = {
        "canary_id": "canary-001",
        "approved_executor_id": EXECUTOR_ID,
        "approved_account_id": ACCOUNT_ID,
        "approved_broker_server": "Broker-Demo",
        "approved_canonical_symbol": "EURUSD",
        "approved_broker_symbol": BROKER_SYMBOL,
    }
    payload["order"] = {**payload["order"], "magic": ENGINEERING_DEMO_CANARY_MAGIC, "comment_tag": "W15D0:ABCDEF12"}
    payload["guards"] = {
        "expected_margin_mode": "HEDGING",
        "account_snapshot_id": SNAPSHOT_ID,
        "balance_snapshot": 1000,
        "equity_snapshot": 1000,
        "max_spread_points": 25,
        "max_price_drift_points": 15,
    }
    return ExecutionCommandV1.model_validate(payload)


def test_d3_binding_function_is_bound_for_consistent_inputs_and_reuses_real_command_fields() -> None:
    empty = {
        "SNAPSHOT_BINDING_MISMATCH": [],
        "CAPABILITY_BINDING_MISMATCH": [],
        "SYMBOL_CAPABILITY_BINDING_MISMATCH": [],
    }
    assert candidate_binding_failures(**_parsed()) == empty
    canary = _canary_command()
    assert candidate_binding_failures(**_parsed(command=canary)) == empty
    assert command_snapshot_ref(canary) == ("command.guards.account_snapshot_id", SNAPSHOT_ID)
    assert command_snapshot_ref(ExecutionCommandV1.model_validate(command())) == (
        "command.guards.risk_snapshot_id",
        SNAPSHOT_ID,
    )
    assert command_source_symbols(canary) == ("command.source.approved_", "EURUSD", BROKER_SYMBOL)
    assert command_source_symbols(ExecutionCommandV1.model_validate(command())) is None  # signal_json: no field
    shadow = ShadowAcceptanceSource(
        acceptance_run_id="run-001", phase="A1", canonical_symbol="GBPUSD", broker_symbol="G"
    )
    assert command_source_symbols(canary.model_copy(update={"source": shadow})) == ("command.source.", "GBPUSD", "G")
    shadow_guards = ShadowAcceptanceGuards(
        expected_margin_mode=MarginMode.HEDGING, account_snapshot_id=SNAPSHOT_ID, balance_snapshot=1, equity_snapshot=1
    )
    assert command_snapshot_ref(canary.model_copy(update={"guards": shadow_guards})) == ("command.guards", None)


@pytest.mark.parametrize(
    ("field", "value", "ref"),
    [
        ("approved_canonical_symbol", "GBPUSD", "command.source.approved_canonical_symbol"),
        ("approved_broker_symbol", "EURUSD.b", "command.source.approved_broker_symbol"),
    ],
)
def test_d3c_source_approved_symbol_link_is_checked(field: str, value: str, ref: str) -> None:
    """ExecutionCommandV1 already refuses approved != order at parse time; the binding re-checks it independently."""

    canary = _canary_command()
    tampered = canary.model_copy(update={"source": canary.source.model_copy(update={field: value})})
    failures = candidate_binding_failures(**_parsed(command=tampered))
    assert failures["SYMBOL_CAPABILITY_BINDING_MISMATCH"] == [ref]
    assert failures["SNAPSHOT_BINDING_MISMATCH"] == failures["CAPABILITY_BINDING_MISMATCH"] == []
    guards = canary.guards.model_copy(update={"account_snapshot_id": OTHER_S_ID})
    assert candidate_binding_failures(**_parsed(command=canary.model_copy(update={"guards": guards})))[
        "SNAPSHOT_BINDING_MISMATCH"
    ] == ["command.guards.account_snapshot_id"]


@pytest.mark.parametrize("b5_volume_min", [Decimal("0.02"), None])
def test_d3b_b5_volume_min_input_must_be_the_r9_and_pinned_s_volume_min(b5_volume_min: Decimal | None) -> None:
    failures = candidate_binding_failures(**_parsed(b5_volume_min=b5_volume_min))
    assert failures["CAPABILITY_BINDING_MISMATCH"] == ["b5.volume_min"]


def test_d3_invalid_r9_or_manifest_fails_every_link_closed() -> None:
    no_r9 = candidate_binding_failures(**_parsed(r9_envelope=None))
    assert all(no_r9[reason] for reason in no_r9)
    no_manifest = candidate_binding_failures(**_parsed(manifest=None))
    assert no_manifest["SNAPSHOT_BINDING_MISMATCH"] == [
        "candidate_manifest.pinned_snapshot_id",
        "candidate_manifest.pinned_snapshot_sha256",
    ]
    assert no_manifest["SYMBOL_CAPABILITY_BINDING_MISMATCH"] == ["candidate_manifest.canonical_symbol"]
    assert no_manifest["CAPABILITY_BINDING_MISMATCH"] == []
    # Absent on both sides is never equal: None == None does not bind.
    nothing = candidate_binding_failures(
        **_parsed(
            r9_envelope=None,
            manifest=None,
            b5_volume_min=None,
            snapshot=AccountSnapshotV1.model_validate(snapshot(symbols=[])),
        )
    )
    assert "candidate_manifest.pinned_snapshot_id" in nothing["SNAPSHOT_BINDING_MISMATCH"]
    assert nothing["CAPABILITY_BINDING_MISMATCH"] == [
        "pinned_snapshot.symbols.volume_min",
        "b5.volume_min",
        "pinned_snapshot.symbols.volume_step",
    ]
    assert "candidate_manifest.canonical_symbol" in nothing["SYMBOL_CAPABILITY_BINDING_MISMATCH"]


def test_missing_candidate_manifest_is_not_executed_never_reconciled() -> None:
    payload = evidence()
    del payload["candidate_manifest"]
    report = run(payload)
    assert report["status"] == NOT_EXECUTED
    assert report["missing_evidence"] == ["candidate_manifest"]
    assert report["breaks"] == []
    assert report["candidate_binding"] == {
        "SNAPSHOT_BINDING": NOT_EXECUTED,
        "CAPABILITY_BINDING": NOT_EXECUTED,
        "SYMBOL_CAPABILITY_BINDING": NOT_EXECUTED,
        "bound_snapshot_s": BOUND_S,
    }
    assert report["acceptance"]["BROKER_TRUTH_RECONCILED"] is False
    assert _g6(report) == (False, "SNAPSHOT_BINDING_MISMATCH")


@pytest.mark.parametrize(
    "manifest",
    [
        candidate_manifest(pinned_snapshot_sha256="sha256:" + EXACT_S_SNAPSHOT_SHA256),
        candidate_manifest(schema_version="wolf15.demo-canary.candidate-manifest.v0"),
        {**candidate_manifest(), "extra": 1},
        {key: value for key, value in candidate_manifest().items() if key != "pinned_snapshot_sha256"},
        ["not", "a", "mapping"],
    ],
)
def test_invalid_candidate_manifest_is_a_break_and_never_binds(manifest: Any) -> None:
    report = run(evidence(candidate_manifest=manifest))
    assert codes(report) == {
        "CANDIDATE_MANIFEST_INVALID",
        "SNAPSHOT_BINDING_MISMATCH",
        "SYMBOL_CAPABILITY_BINDING_MISMATCH",
    }
    assert report["status"] == "NOT_RECONCILED"
    assert _g6(report) == (False, "SNAPSHOT_BINDING_MISMATCH")


@pytest.mark.parametrize(
    "overrides", [{"tradeplan_candidate_id": "5scr-plan:" + "f" * 32}, {"tradeplan_candidate_revision": 4}]
)
def test_candidate_manifest_must_be_the_ledger_candidate(overrides: dict[str, Any]) -> None:
    report = run(evidence(candidate_manifest=candidate_manifest(**overrides)))
    assert codes(report) == {"CANDIDATE_MANIFEST_CANDIDATE_MISMATCH"}
    assert report["candidate_binding"] == ALL_BOUND
    assert _g6(report) == (False, "BROKER_TRUTH_NOT_RECONCILED")


def test_missing_ledger_exact_s_leaves_the_snapshot_binding_not_executed() -> None:
    report = run(evidence(v31_side_ledger=chain_ledger(exact_s=None)))
    assert report["candidate_binding"]["SNAPSHOT_BINDING"] == NOT_EXECUTED
    assert report["candidate_binding"]["CAPABILITY_BINDING"] is True
    assert report["candidate_binding"]["SYMBOL_CAPABILITY_BINDING"] is True
    assert report["breaks"] == []
    assert _g6(report) == (False, "SNAPSHOT_BINDING_MISMATCH")


# ---- runtime candidate binding: NOT_MEASURED unless supplied as evidence -------------------------------------------

RUNTIME = {"EA_EX5_SHA256": "7" * 64, "EA_PRESET_SHA256": "8" * 64, "DEMO_ACCOUNT_BINDING": ACCOUNT_ID}


def test_runtime_candidate_binding_defaults_to_not_measured_and_blocks_g6_ready_for_demo() -> None:
    report = run(evidence())
    assert _g6(report) == (True, "READY")
    assert report["runtime_candidate_binding"] == {
        "EA_EX5_SHA256": "NOT_MEASURED",
        "EA_PRESET_SHA256": "NOT_MEASURED",
        "DEMO_ACCOUNT_BINDING": "NOT_MEASURED",
        "G6_READY_FOR_DEMO": False,
    }


def test_runtime_candidate_binding_all_measured_and_g6_ready_is_ready_for_demo() -> None:
    report = run(evidence(runtime_candidate_binding=dict(RUNTIME)))
    assert report["runtime_candidate_binding"] == {**RUNTIME, "G6_READY_FOR_DEMO": True}
    assert report["status"] == "RECONCILED"
    not_g6 = run(
        evidence(
            runtime_candidate_binding=dict(RUNTIME), candidate_manifest=candidate_manifest(canonical_symbol="GBPUSD")
        )
    )
    assert not_g6["acceptance"]["G6_READY"] is False
    assert not_g6["runtime_candidate_binding"] == {**RUNTIME, "G6_READY_FOR_DEMO": False}


@pytest.mark.parametrize("name", ["EA_EX5_SHA256", "EA_PRESET_SHA256", "DEMO_ACCOUNT_BINDING"])
def test_each_unmeasured_runtime_binding_blocks_g6_ready_for_demo(name: str) -> None:
    for supplied in ({k: v for k, v in RUNTIME.items() if k != name}, {**RUNTIME, name: None}):
        report = run(evidence(runtime_candidate_binding=supplied))
        assert report["runtime_candidate_binding"][name] == "NOT_MEASURED"
        assert report["runtime_candidate_binding"]["G6_READY_FOR_DEMO"] is False
        assert _g6(report) == (True, "READY")


def test_runtime_binding_placeholder_value_is_never_measured() -> None:
    report = run(evidence(runtime_candidate_binding={**RUNTIME, "DEMO_ACCOUNT_BINDING": "NOT_MEASURED"}))
    assert report["runtime_candidate_binding"]["G6_READY_FOR_DEMO"] is False


@pytest.mark.parametrize(
    "supplied",
    [
        {**RUNTIME, "EA_EX5_SHA256": "sha256:" + "7" * 64},
        {**RUNTIME, "EA_PRESET_SHA256": "X" * 64},
        {**RUNTIME, "DEMO_ACCOUNT_BINDING": ""},
        {**RUNTIME, "EXTRA": "1"},
        "not-a-mapping",
    ],
)
def test_invalid_runtime_binding_is_a_break_and_reports_not_measured(supplied: Any) -> None:
    report = run(evidence(runtime_candidate_binding=supplied))
    assert codes(report) == {"RUNTIME_CANDIDATE_BINDING_INVALID"}
    assert report["runtime_candidate_binding"] == {
        "EA_EX5_SHA256": "NOT_MEASURED",
        "EA_PRESET_SHA256": "NOT_MEASURED",
        "DEMO_ACCOUNT_BINDING": "NOT_MEASURED",
        "G6_READY_FOR_DEMO": False,
    }
    assert report["status"] == "NOT_RECONCILED"
