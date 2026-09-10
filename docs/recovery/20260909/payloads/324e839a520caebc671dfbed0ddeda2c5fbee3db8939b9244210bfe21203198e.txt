from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
SHADOW_EA = ROOT / "ea_interface" / "wolf15_executor" / "Wolf15_DumbExecutor_Shadow.mq5"
DEMO_EA = ROOT / "ea_interface" / "wolf15_executor" / "Wolf15_DumbExecutor_Demo.mq5"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function(source: str, name: str, next_name: str) -> str:
    start = source.index(name)
    end = source.index(next_name, start)
    return source[start:end]


def test_shadow_artifact_still_has_no_broker_submit_primitive() -> None:
    shadow = _source(SHADOW_EA)

    assert "OrderSend(" not in shadow
    assert "SHADOW ONLY" in shadow


def test_demo_is_a_separate_explicitly_armed_demo_only_artifact() -> None:
    demo = _source(DEMO_EA)

    assert DEMO_EA != SHADOW_EA
    assert '#include "Wolf15_DumbExecutor_Shadow.mq5"' in demo
    assert "InpDemoExecutionArmed    = false" in demo
    assert "ACCOUNT_TRADE_MODE_DEMO" in demo
    assert 'requested_mode\\":\\"DEMO' in demo
    assert 'JsonValue(response, "execution_mode") != "DEMO"' in demo
    assert "W15_DEMO_VERSION" in demo


def test_demo_command_lineage_is_not_strategy_or_real_money_authority() -> None:
    demo = _source(DEMO_EA)

    assert 'W15_DEMO_SOURCE "ENGINEERING_DEMO_CANARY"' in demo
    assert 'W15_DEMO_SCHEMA "wolf15.mt5.engineering-demo-canary.v1"' in demo
    assert 'W15_DEMO_AUTHORITY "WOLF15_ENGINEERING_DEMO_OPERATOR_V1"' in demo
    assert 'JsonValue(json, "strategy_authority", "missing") != "false"' in demo
    assert 'JsonValue(json, "strategy_scorecard_eligible", "missing") != "false"' in demo
    assert 'JsonValue(json, "research_result_eligible", "missing") != "false"' in demo
    assert 'JsonValue(json, "live_real_money_allowed", "missing") != "false"' in demo
    assert 'JsonValue(json, "demo_only", "missing") != "true"' in demo
    assert 'JsonValue(json, "order_role") != "PARENT"' in demo


def test_demo_hard_locks_executor_account_broker_and_one_symbol() -> None:
    demo = _source(DEMO_EA)

    assert 'JsonValue(json, "approved_executor_id") != InpExecutorId' in demo
    assert 'JsonValue(json, "approved_account_id") != InpExpectedAccountId' in demo
    assert 'JsonValue(json, "approved_broker_server") != InpExpectedBrokerServer' in demo
    assert 'JsonValue(json, "approved_canonical_symbol") != InpApprovedCanonicalSymbol' in demo
    assert 'JsonValue(json, "approved_broker_symbol") != InpApprovedBrokerSymbol' in demo
    assert 'StringToInteger(JsonValue(json, "magic")) != W15_DEMO_MAGIC' in demo
    assert 'JsonValue(json, "time_in_force") != "GTC"' in demo
    assert 'JsonValue(json, "expected_margin_mode") != MarginModeName()' in demo
    assert 'JsonValue(json, "balance_snapshot")' in demo
    assert 'JsonValue(json, "equity_snapshot")' in demo
    assert "PositionsTotal() != 0 || OrdersTotal() != 0" in demo


def test_demo_verifies_signed_envelope_before_command_validation() -> None:
    poll = _function(demo := _source(DEMO_EA), "void PollOneDemoCommand()", "bool RecoverDemoState()")

    assert poll.index("VerifySignedEnvelope(") < poll.index("ValidateDemoCommand(")
    assert "QUARANTINED" in poll
    assert "ExecuteDemoCommand(state)" in poll
    assert "EXECUTOR_COMMAND_SIGNING_SECRET" not in demo


def test_ordercheck_and_durable_boundary_precede_the_only_ordersend() -> None:
    demo = _source(DEMO_EA)
    checked = _function(demo, "bool BuildCheckedDemoRequest(", "bool ExecuteDemoCommand(")
    execute = _function(demo, "bool ExecuteDemoCommand(", "void PollOneDemoCommand()")

    assert demo.count("OrderSend(") == 1
    assert "ValidateDemoCommand(" in checked
    assert "OrderCheck(" in checked
    assert execute.count("BuildCheckedDemoRequest(") == 2
    submit_ack = execute.index('SendDemoReport(state, "SUBMITTING"')
    final_check = execute.index("BuildCheckedDemoRequest(", submit_ack)
    assert execute.index("BuildCheckedDemoRequest(") < submit_ack < final_check
    assert final_check < execute.index("state.submit_attempted = true")
    assert "DEMO_FINAL_PREFLIGHT_REJECTED" in execute
    assert execute.index("state.submit_attempted = true") < execute.index("SaveDemoState(state")
    assert execute.index("SaveDemoState(state") < execute.index("OrderSend(")
    assert execute.index("PERSIST_BEFORE_ORDERSEND") < execute.index("OrderSend(")
    assert "ATTEMPT_1_OF_1" in execute
    assert "request.sl" in checked
    assert "request.tp" in checked


def test_ordercheck_rejection_has_no_submit_path() -> None:
    checked = _function(_source(DEMO_EA), "bool BuildCheckedDemoRequest(", "bool ExecuteDemoCommand(")
    execute = _function(_source(DEMO_EA), "bool ExecuteDemoCommand(", "void PollOneDemoCommand()")
    check_branch = execute[: execute.index('SendDemoReport(state, "SUBMITTING"')]

    assert "OrderCheck(" in checked
    assert "PREFLIGHT_REJECTED" in check_branch
    assert "OrderSend(" not in check_branch


def test_demo_reports_broker_retcode_and_exact_signed_order_evidence() -> None:
    demo = _source(DEMO_EA)
    prepare = _function(demo, "bool PrepareDemoReport(", "bool PostPreparedDemoReport(")
    execute = _function(demo, "bool ExecuteDemoCommand(", "void PollOneDemoCommand()")

    assert r"\"retcode\":%s" in prepare
    assert "NullableRetcode(broker_retcode)" in prepare
    assert 'JsonValue(command, "volume")' in prepare
    assert 'JsonValue(command, "entry_price")' in prepare
    assert 'JsonValue(command, "stop_loss")' in prepare
    assert 'JsonValue(command, "take_profit")' in prepare
    assert "result.volume" in execute
    assert "DEMO_ONE_ORDER_PARTIAL_REQUIRES_RECONCILIATION" in execute
    assert "DEMO_ONE_ORDER_FILL_REQUIRES_HISTORY_RECONCILIATION" in execute
    assert "DEMO_DEAL_EVIDENCE_INCOMPLETE" in execute
    assert "DEMO_FILL_VOLUME_EXCEEDS_COMMAND" in execute


def test_restart_never_retries_ordersend_and_requires_reconciliation() -> None:
    demo = _source(DEMO_EA)
    recovery = _function(demo, "bool RecoverDemoState()", "int OnInit()")

    assert "OrderSend(" not in recovery
    assert "submit_attempted" in recovery
    assert "DEMO_RESTART_BEFORE_SUBMIT" in recovery
    assert "AMBIGUOUS_REQUIRES_RECONCILIATION" in recovery
    assert "ReconcileDemoBrokerState" in recovery
    assert 'command_state == "BROKER_ACCEPTED" || command_state == "AMBIGUOUS"' in recovery
    assert "DEMO_RESTART_ORDER_WITHOUT_RETCODE" in recovery


def test_demo_reconciles_exact_broker_history_before_resolving_ambiguity() -> None:
    demo = _source(DEMO_EA)
    reconcile = _function(demo, "bool ReconcileDemoBrokerState", "bool ExecuteDemoCommand")

    assert "HistorySelect(" in reconcile
    assert "HistoryOrdersTotal()" in reconcile
    assert "HistoryOrderGetTicket(" in reconcile
    assert "HistoryDealsTotal()" in reconcile
    assert "HistoryDealGetTicket(" in reconcile
    assert "PositionsTotal()" in reconcile
    assert "OrdersTotal()" in reconcile
    assert "ORDER_MAGIC" in reconcile
    assert "DEAL_MAGIC" in reconcile
    assert "W15_DEMO_MAGIC" in reconcile
    assert 'JsonValue(state.command_json, "comment_tag")' in reconcile
    assert "DEMO_RECONCILIATION_MULTIPLE_ORDERS" in reconcile
    assert "DEMO_RECONCILIATION_MULTIPLE_DEALS" in reconcile
    assert "DEMO_RECONCILIATION_MULTIPLE_POSITIONS" in reconcile
    assert "DEMO_RECONCILIATION_PROTECTION_MISMATCH" in reconcile
    assert "POSITION_SL" in reconcile
    assert "POSITION_TP" in reconcile
    assert "OrderSend(" not in reconcile


def test_demo_has_hmac_durable_state_and_trade_transaction_reconciliation() -> None:
    demo = _source(DEMO_EA)

    assert "HmacSha256Bytes" in demo
    assert "ComputeDemoIntegrityTag" in demo
    assert "FileMove(DemoStateTempPath(), 0, DemoStatePath(), FILE_REWRITE)" in demo
    assert "pending_report_body" in demo
    assert "BuildPendingOrdersJson" in demo
    assert '\\"broker_ledger_reconciled\\":false' in demo
    assert '\\"broker_ledger_reconciled\\":true' not in demo
    assert "void OnTradeTransaction" in demo
    assert "g_trade_event_pending = true" in demo


def test_demo_source_contains_no_strategy_decision_logic() -> None:
    demo = _source(DEMO_EA).lower()

    forbidden = (
        "directional_thesis",
        "microboost",
        "pairadmission",
        "strategyanalysisadmission",
        "take profit selection",
        "risk sizing",
        "trailing stop",
    )
    for token in forbidden:
        assert token not in demo
